/**
 * texfury_native.cpp
 *
 * C-API wrapper around stb_image, stb_image_resize2, rgbcx (bc7enc_rdo)
 * for Python ctypes consumption.
 *
 * Provides: image loading, resizing, mipmap generation, BC1/3/4/5/7
 * compression, DDS read/write.
 */

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

// ── stb implementations ─────────────────────────────────────────────────────
#define STB_IMAGE_IMPLEMENTATION
#define STBI_NO_STDIO  // we handle file I/O ourselves for wide-char paths
#include "stb_image.h"

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include "stb_image_resize2.h"

// ── bc7enc_rdo / rgbcx ──────────────────────────────────────────────────────
#include "rgbcx.h"
#include "bc7e_ispc.h"
#include "bc7decomp.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <algorithm>

// ── Export macro ─────────────────────────────────────────────────────────────
#define TF_API extern "C" __declspec(dllexport)

// ── Image handle ─────────────────────────────────────────────────────────────
struct TfImage {
    uint8_t* pixels;    // RGBA, owned
    int      width;
    int      height;
    int      channels;  // original channel count before forcing RGBA
    bool     owned;     // if true, we free pixels on destroy
};

// ── Compressed texture handle ────────────────────────────────────────────────
struct TfCompressed {
    uint8_t* data;
    size_t   size;
    int      width;
    int      height;
    int      format;      // TfBCFormat enum value
    int      mip_count;
    size_t*  mip_offsets;  // offset into data for each mip
    size_t*  mip_sizes;    // byte size of each mip
};

// ── Enums ────────────────────────────────────────────────────────────────────
enum TfBCFormat {
    TF_BC1 = 0,
    TF_BC3 = 1,
    TF_BC4 = 2,
    TF_BC5 = 3,
    TF_BC7 = 4,
    TF_A8R8G8B8 = 5,  // Uncompressed 32-bit BGRA
};

// ── Globals ──────────────────────────────────────────────────────────────────
static bool g_initialized = false;

static void ensure_init() {
    if (!g_initialized) {
        rgbcx::init();
        ispc::bc7e_compress_block_init();
        g_initialized = true;
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

static bool is_block_compressed(TfBCFormat fmt) {
    return fmt != TF_A8R8G8B8;
}

static int block_byte_size(TfBCFormat fmt) {
    switch (fmt) {
        case TF_BC1: case TF_BC4: return 8;
        default: return 16;
    }
}

static size_t calc_mip_size(int w, int h, TfBCFormat fmt) {
    if (fmt == TF_A8R8G8B8) {
        return (size_t)w * h * 4;
    }
    int bw = (w + 3) / 4;
    int bh = (h + 3) / 4;
    if (bw < 1) bw = 1;
    if (bh < 1) bh = 1;
    return (size_t)bw * bh * block_byte_size(fmt);
}

static int calc_mip_count(int w, int h, int min_dim) {
    int count = 1;
    while (w > min_dim || h > min_dim) {
        w = (w > 1) ? w / 2 : 1;
        h = (h > 1) ? h / 2 : 1;
        count++;
    }
    return count;
}

static uint32_t next_pot(uint32_t v) {
    if (v == 0) return 1;
    v--;
    v |= v >> 1; v |= v >> 2; v |= v >> 4;
    v |= v >> 8; v |= v >> 16;
    return v + 1;
}

// Read a file into memory (supports wide paths on Windows)
static uint8_t* read_file(const wchar_t* path, size_t* out_size) {
    HANDLE hFile = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ,
                               NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hFile == INVALID_HANDLE_VALUE) return nullptr;

    LARGE_INTEGER li;
    GetFileSizeEx(hFile, &li);
    size_t sz = (size_t)li.QuadPart;

    uint8_t* buf = (uint8_t*)malloc(sz);
    if (!buf) { CloseHandle(hFile); return nullptr; }

    DWORD read;
    ReadFile(hFile, buf, (DWORD)sz, &read, NULL);
    CloseHandle(hFile);

    if (read != sz) { free(buf); return nullptr; }
    *out_size = sz;
    return buf;
}

static bool write_file(const wchar_t* path, const void* data, size_t size) {
    HANDLE hFile = CreateFileW(path, GENERIC_WRITE, 0,
                               NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hFile == INVALID_HANDLE_VALUE) return false;

    DWORD written;
    WriteFile(hFile, data, (DWORD)size, &written, NULL);
    CloseHandle(hFile);
    return written == size;
}

// ── Image lifecycle ──────────────────────────────────────────────────────────

TF_API TfImage* tf_load_image(const wchar_t* path) {
    size_t file_size = 0;
    uint8_t* file_data = read_file(path, &file_size);
    if (!file_data) return nullptr;

    int w, h, ch;
    uint8_t* pixels = stbi_load_from_memory(file_data, (int)file_size,
                                             &w, &h, &ch, 4);
    free(file_data);
    if (!pixels) return nullptr;

    auto* img = new TfImage();
    img->pixels = pixels;
    img->width = w;
    img->height = h;
    img->channels = ch;
    img->owned = true;
    return img;
}

TF_API TfImage* tf_load_image_memory(const uint8_t* data, size_t size) {
    int w, h, ch;
    uint8_t* pixels = stbi_load_from_memory(data, (int)size, &w, &h, &ch, 4);
    if (!pixels) return nullptr;

    auto* img = new TfImage();
    img->pixels = pixels;
    img->width = w;
    img->height = h;
    img->channels = ch;
    img->owned = true;
    return img;
}

TF_API TfImage* tf_create_image(int width, int height, const uint8_t* rgba_data) {
    size_t sz = (size_t)width * height * 4;
    uint8_t* pixels = (uint8_t*)malloc(sz);
    if (!pixels) return nullptr;
    memcpy(pixels, rgba_data, sz);

    auto* img = new TfImage();
    img->pixels = pixels;
    img->width = width;
    img->height = height;
    img->channels = 4;
    img->owned = true;
    return img;
}

TF_API void tf_free_image(TfImage* img) {
    if (!img) return;
    if (img->owned && img->pixels) stbi_image_free(img->pixels);
    delete img;
}

TF_API int tf_image_width(const TfImage* img) { return img ? img->width : 0; }
TF_API int tf_image_height(const TfImage* img) { return img ? img->height : 0; }
TF_API int tf_image_channels(const TfImage* img) { return img ? img->channels : 0; }
TF_API const uint8_t* tf_image_pixels(const TfImage* img) { return img ? img->pixels : nullptr; }

// ── Image queries ────────────────────────────────────────────────────────────

TF_API int tf_has_transparency(const TfImage* img) {
    if (!img || !img->pixels) return 0;
    // Original image had no alpha channel
    if (img->channels < 4) return 0;

    size_t count = (size_t)img->width * img->height;
    for (size_t i = 0; i < count; i++) {
        if (img->pixels[i * 4 + 3] < 255) return 1;
    }
    return 0;
}

TF_API int tf_is_power_of_two(int width, int height) {
    return (width > 0 && (width & (width - 1)) == 0 &&
            height > 0 && (height & (height - 1)) == 0) ? 1 : 0;
}

TF_API int tf_next_power_of_two(int v) {
    return (int)next_pot((uint32_t)v);
}

// ── Image transforms ─────────────────────────────────────────────────────────

TF_API TfImage* tf_resize(const TfImage* img, int new_w, int new_h) {
    if (!img || !img->pixels || new_w <= 0 || new_h <= 0) return nullptr;

    uint8_t* out = (uint8_t*)malloc((size_t)new_w * new_h * 4);
    if (!out) return nullptr;

    stbir_resize_uint8_srgb(img->pixels, img->width, img->height, 0,
                             out, new_w, new_h, 0, STBIR_RGBA);

    auto* r = new TfImage();
    r->pixels = out;
    r->width = new_w;
    r->height = new_h;
    r->channels = 4;
    r->owned = true;
    return r;
}

TF_API TfImage* tf_resize_to_pot(const TfImage* img) {
    if (!img) return nullptr;
    int pw = (int)next_pot((uint32_t)img->width);
    int ph = (int)next_pot((uint32_t)img->height);
    if (pw == img->width && ph == img->height) {
        // Already POT, return a copy
        return tf_create_image(img->width, img->height, img->pixels);
    }
    return tf_resize(img, pw, ph);
}

// ── Block compression ────────────────────────────────────────────────────────

static void compress_blocks_bc1(const uint8_t* rgba, int w, int h,
                                 uint8_t* out, int quality_level) {
    int bw = (w + 3) / 4;
    int bh = (h + 3) / 4;
    uint8_t block[64]; // 4x4 RGBA

    for (int by = 0; by < bh; by++) {
        for (int bx = 0; bx < bw; bx++) {
            // Extract 4x4 block with clamping
            for (int y = 0; y < 4; y++) {
                int py = std::min(by * 4 + y, h - 1);
                for (int x = 0; x < 4; x++) {
                    int px = std::min(bx * 4 + x, w - 1);
                    memcpy(&block[(y * 4 + x) * 4],
                           &rgba[(py * w + px) * 4], 4);
                }
            }
            rgbcx::encode_bc1(quality_level, out, block, true, false);
            out += 8;
        }
    }
}

static void compress_blocks_bc3(const uint8_t* rgba, int w, int h,
                                 uint8_t* out, int quality_level) {
    int bw = (w + 3) / 4;
    int bh = (h + 3) / 4;
    uint8_t block[64];

    for (int by = 0; by < bh; by++) {
        for (int bx = 0; bx < bw; bx++) {
            for (int y = 0; y < 4; y++) {
                int py = std::min(by * 4 + y, h - 1);
                for (int x = 0; x < 4; x++) {
                    int px = std::min(bx * 4 + x, w - 1);
                    memcpy(&block[(y * 4 + x) * 4],
                           &rgba[(py * w + px) * 4], 4);
                }
            }
            rgbcx::encode_bc3(quality_level, out, block);
            out += 16;
        }
    }
}

static void compress_blocks_bc4(const uint8_t* rgba, int w, int h,
                                 uint8_t* out) {
    int bw = (w + 3) / 4;
    int bh = (h + 3) / 4;
    uint8_t block[64];

    for (int by = 0; by < bh; by++) {
        for (int bx = 0; bx < bw; bx++) {
            for (int y = 0; y < 4; y++) {
                int py = std::min(by * 4 + y, h - 1);
                for (int x = 0; x < 4; x++) {
                    int px = std::min(bx * 4 + x, w - 1);
                    memcpy(&block[(y * 4 + x) * 4],
                           &rgba[(py * w + px) * 4], 4);
                }
            }
            rgbcx::encode_bc4(out, block, 4);
            out += 8;
        }
    }
}

static void compress_blocks_bc5(const uint8_t* rgba, int w, int h,
                                 uint8_t* out) {
    int bw = (w + 3) / 4;
    int bh = (h + 3) / 4;
    uint8_t block[64];

    for (int by = 0; by < bh; by++) {
        for (int bx = 0; bx < bw; bx++) {
            for (int y = 0; y < 4; y++) {
                int py = std::min(by * 4 + y, h - 1);
                for (int x = 0; x < 4; x++) {
                    int px = std::min(bx * 4 + x, w - 1);
                    memcpy(&block[(y * 4 + x) * 4],
                           &rgba[(py * w + px) * 4], 4);
                }
            }
            rgbcx::encode_bc5(out, block, 0, 1, 4);
            out += 16;
        }
    }
}

static void compress_blocks_bc7(const uint8_t* rgba, int w, int h,
                                 uint8_t* out, int quality_level) {
    int bw = (w + 3) / 4;
    int bh = (h + 3) / 4;
    int total_blocks = bw * bh;

    // Prepare block pixels as uint32 RGBA
    uint32_t* block_pixels = (uint32_t*)malloc((size_t)total_blocks * 16 * sizeof(uint32_t));
    if (!block_pixels) return;

    for (int by = 0; by < bh; by++) {
        for (int bx = 0; bx < bw; bx++) {
            int block_idx = by * bw + bx;
            for (int y = 0; y < 4; y++) {
                int py = std::min(by * 4 + y, h - 1);
                for (int x = 0; x < 4; x++) {
                    int px = std::min(bx * 4 + x, w - 1);
                    const uint8_t* src = &rgba[(py * w + px) * 4];
                    block_pixels[block_idx * 16 + y * 4 + x] =
                        src[0] | (src[1] << 8) | (src[2] << 16) | (src[3] << 24);
                }
            }
        }
    }

    ispc::bc7e_compress_block_params params;
    switch (quality_level) {
        case 0: ispc::bc7e_compress_block_params_init_ultrafast(&params, false); break;
        case 1: ispc::bc7e_compress_block_params_init_veryfast(&params, false); break;
        case 2: ispc::bc7e_compress_block_params_init_fast(&params, false); break;
        case 3: ispc::bc7e_compress_block_params_init_basic(&params, false); break;
        case 4: ispc::bc7e_compress_block_params_init_slow(&params, false); break;
        case 5: ispc::bc7e_compress_block_params_init_veryslow(&params, false); break;
        default: ispc::bc7e_compress_block_params_init_slowest(&params, false); break;
    }

    // Compress in batches of 64 blocks
    int processed = 0;
    while (processed < total_blocks) {
        int batch = std::min(64, total_blocks - processed);
        ispc::bc7e_compress_blocks(
            batch,
            (uint64_t*)(out + (size_t)processed * 16),
            &block_pixels[processed * 16],
            &params);
        processed += batch;
    }

    free(block_pixels);
}

// ── Main compress function ───────────────────────────────────────────────────

TF_API TfCompressed* tf_compress(const TfImage* img, int format,
                                  int generate_mipmaps, int min_mip_dim,
                                  float quality) {
    if (!img || !img->pixels) return nullptr;
    ensure_init();

    TfBCFormat fmt = (TfBCFormat)format;
    int w = img->width;
    int h = img->height;

    // Quality to encoder level
    int rgbx_level = (int)(quality * rgbcx::MAX_LEVEL);
    if (rgbx_level > (int)rgbcx::MAX_LEVEL) rgbx_level = rgbcx::MAX_LEVEL;
    int bc7_level = (int)(quality * 6.0f);
    if (bc7_level > 6) bc7_level = 6;

    // Calculate mip count
    int mip_count = 1;
    if (generate_mipmaps) {
        int min_d = (min_mip_dim > 0) ? min_mip_dim : 4;
        mip_count = calc_mip_count(w, h, min_d);
    }

    // Calculate total size
    size_t total_size = 0;
    size_t* offsets = (size_t*)malloc(mip_count * sizeof(size_t));
    size_t* sizes = (size_t*)malloc(mip_count * sizeof(size_t));
    {
        int mw = w, mh = h;
        for (int i = 0; i < mip_count; i++) {
            offsets[i] = total_size;
            sizes[i] = calc_mip_size(mw, mh, fmt);
            total_size += sizes[i];
            mw = (mw > 1) ? mw / 2 : 1;
            mh = (mh > 1) ? mh / 2 : 1;
        }
    }

    uint8_t* compressed_data = (uint8_t*)malloc(total_size);
    if (!compressed_data) { free(offsets); free(sizes); return nullptr; }

    // Compress each mip level
    const uint8_t* current_rgba = img->pixels;
    uint8_t* resized_buf = nullptr;
    int mw = w, mh = h;

    for (int mip = 0; mip < mip_count; mip++) {
        const uint8_t* src = current_rgba;

        if (mip > 0) {
            // Downsample from original for better quality
            if (resized_buf) free(resized_buf);
            resized_buf = (uint8_t*)malloc((size_t)mw * mh * 4);
            stbir_resize_uint8_srgb(img->pixels, w, h, 0,
                                     resized_buf, mw, mh, 0, STBIR_RGBA);
            src = resized_buf;
        }

        uint8_t* dst = compressed_data + offsets[mip];
        switch (fmt) {
            case TF_BC1: compress_blocks_bc1(src, mw, mh, dst, rgbx_level); break;
            case TF_BC3: compress_blocks_bc3(src, mw, mh, dst, rgbx_level); break;
            case TF_BC4: compress_blocks_bc4(src, mw, mh, dst); break;
            case TF_BC5: compress_blocks_bc5(src, mw, mh, dst); break;
            case TF_BC7: compress_blocks_bc7(src, mw, mh, dst, bc7_level); break;
            case TF_A8R8G8B8: {
                // Swizzle RGBA → BGRA (A8R8G8B8 in little-endian = BGRA bytes)
                size_t px_count = (size_t)mw * mh;
                for (size_t p = 0; p < px_count; p++) {
                    dst[p * 4 + 0] = src[p * 4 + 2]; // B
                    dst[p * 4 + 1] = src[p * 4 + 1]; // G
                    dst[p * 4 + 2] = src[p * 4 + 0]; // R
                    dst[p * 4 + 3] = src[p * 4 + 3]; // A
                }
                break;
            }
        }

        mw = (mw > 1) ? mw / 2 : 1;
        mh = (mh > 1) ? mh / 2 : 1;
    }

    if (resized_buf) free(resized_buf);

    auto* result = new TfCompressed();
    result->data = compressed_data;
    result->size = total_size;
    result->width = w;
    result->height = h;
    result->format = format;
    result->mip_count = mip_count;
    result->mip_offsets = offsets;
    result->mip_sizes = sizes;
    return result;
}

TF_API void tf_free_compressed(TfCompressed* c) {
    if (!c) return;
    free(c->data);
    free(c->mip_offsets);
    free(c->mip_sizes);
    delete c;
}

TF_API const uint8_t* tf_compressed_data(const TfCompressed* c) { return c ? c->data : nullptr; }
TF_API size_t tf_compressed_size(const TfCompressed* c) { return c ? c->size : 0; }
TF_API int tf_compressed_width(const TfCompressed* c) { return c ? c->width : 0; }
TF_API int tf_compressed_height(const TfCompressed* c) { return c ? c->height : 0; }
TF_API int tf_compressed_format(const TfCompressed* c) { return c ? c->format : 0; }
TF_API int tf_compressed_mip_count(const TfCompressed* c) { return c ? c->mip_count : 0; }
TF_API size_t tf_compressed_mip_offset(const TfCompressed* c, int mip) {
    return (c && mip >= 0 && mip < c->mip_count) ? c->mip_offsets[mip] : 0;
}
TF_API size_t tf_compressed_mip_size(const TfCompressed* c, int mip) {
    return (c && mip >= 0 && mip < c->mip_count) ? c->mip_sizes[mip] : 0;
}

// ── DDS file I/O ─────────────────────────────────────────────────────────────

// DXGI format mapping
static uint32_t fmt_to_dxgi(TfBCFormat fmt) {
    switch (fmt) {
        case TF_BC1: return 71;       // DXGI_FORMAT_BC1_UNORM
        case TF_BC3: return 77;       // DXGI_FORMAT_BC3_UNORM
        case TF_BC4: return 80;       // DXGI_FORMAT_BC4_UNORM
        case TF_BC5: return 83;       // DXGI_FORMAT_BC5_UNORM
        case TF_BC7: return 98;       // DXGI_FORMAT_BC7_UNORM
        case TF_A8R8G8B8: return 87;  // DXGI_FORMAT_B8G8R8A8_UNORM
        default: return 0;
    }
}

static int dxgi_to_fmt(uint32_t dxgi) {
    switch (dxgi) {
        case 71: return TF_BC1;
        case 77: return TF_BC3;
        case 80: return TF_BC4;
        case 83: return TF_BC5;
        case 98: return TF_BC7;
        case 87: return TF_A8R8G8B8;  // B8G8R8A8_UNORM
        case 28: return TF_A8R8G8B8;  // R8G8B8A8_UNORM (treat as same)
        default: return -1;
    }
}

// FourCC mapping for legacy DDS
static uint32_t fourcc_to_bc(uint32_t fourcc) {
    if (fourcc == 0x31545844) return TF_BC1; // "DXT1"
    if (fourcc == 0x33545844) return TF_BC3; // "DXT3" → treat as BC3
    if (fourcc == 0x35545844) return TF_BC3; // "DXT5"
    if (fourcc == 0x31495441) return TF_BC4; // "ATI1"
    if (fourcc == 0x32495441) return TF_BC5; // "ATI2"
    if (fourcc == 0x30315844) return -2;     // "DX10" → use extended header
    return -1;
}

// DDS header constants
#define DDS_MAGIC 0x20534444
#define DDSD_CAPS 0x1
#define DDSD_HEIGHT 0x2
#define DDSD_WIDTH 0x4
#define DDSD_PIXELFORMAT 0x1000
#define DDSD_MIPMAPCOUNT 0x20000
#define DDSD_LINEARSIZE 0x80000
#define DDPF_ALPHAPIXELS 0x1
#define DDPF_FOURCC 0x4
#define DDPF_RGB 0x40
#define DDSD_PITCH 0x8
#define DDSCAPS_TEXTURE 0x1000
#define DDSCAPS_COMPLEX 0x8
#define DDSCAPS_MIPMAP 0x400000

struct DDS_PIXELFORMAT {
    uint32_t size;
    uint32_t flags;
    uint32_t fourCC;
    uint32_t rgbBitCount;
    uint32_t rBitMask, gBitMask, bBitMask, aBitMask;
};

struct DDS_HEADER {
    uint32_t size;
    uint32_t flags;
    uint32_t height;
    uint32_t width;
    uint32_t pitchOrLinearSize;
    uint32_t depth;
    uint32_t mipMapCount;
    uint32_t reserved1[11];
    DDS_PIXELFORMAT ddspf;
    uint32_t caps;
    uint32_t caps2;
    uint32_t caps3;
    uint32_t caps4;
    uint32_t reserved2;
};

struct DDS_HEADER_DXT10 {
    uint32_t dxgiFormat;
    uint32_t resourceDimension;
    uint32_t miscFlag;
    uint32_t arraySize;
    uint32_t miscFlags2;
};

// Build DDS file in memory from a TfCompressed, returns malloc'd buffer
static uint8_t* build_dds_file(const TfCompressed* c, size_t* out_total) {
    TfBCFormat fmt = (TfBCFormat)c->format;
    bool uncompressed = (fmt == TF_A8R8G8B8);
    bool use_dx10 = !uncompressed && (fmt == TF_BC7 || fmt == TF_BC4 || fmt == TF_BC5);

    DDS_HEADER hdr = {};
    hdr.size = 124;
    hdr.height = c->height;
    hdr.width = c->width;
    hdr.depth = 1;
    hdr.caps = DDSCAPS_TEXTURE;
    hdr.ddspf.size = 32;

    if (uncompressed) {
        hdr.flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_PITCH;
        hdr.pitchOrLinearSize = c->width * 4;  // row pitch
        hdr.ddspf.flags = DDPF_RGB | DDPF_ALPHAPIXELS;
        hdr.ddspf.rgbBitCount = 32;
        hdr.ddspf.rBitMask = 0x00FF0000;
        hdr.ddspf.gBitMask = 0x0000FF00;
        hdr.ddspf.bBitMask = 0x000000FF;
        hdr.ddspf.aBitMask = 0xFF000000;
    } else {
        hdr.flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_LINEARSIZE;
        hdr.pitchOrLinearSize = (uint32_t)c->mip_sizes[0];
        if (use_dx10) {
            hdr.ddspf.flags = DDPF_FOURCC;
            hdr.ddspf.fourCC = 0x30315844; // "DX10"
        } else {
            hdr.ddspf.flags = DDPF_FOURCC;
            hdr.ddspf.fourCC = (fmt == TF_BC1) ? 0x31545844 : 0x35545844;
        }
    }

    if (c->mip_count > 1) {
        hdr.flags |= DDSD_MIPMAPCOUNT;
        hdr.mipMapCount = c->mip_count;
        hdr.caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP;
    }

    DDS_HEADER_DXT10 dx10 = {};
    if (use_dx10) {
        dx10.dxgiFormat = fmt_to_dxgi(fmt);
        dx10.resourceDimension = 3;
        dx10.arraySize = 1;
    }

    size_t header_size = 4 + sizeof(DDS_HEADER) + (use_dx10 ? sizeof(DDS_HEADER_DXT10) : 0);
    size_t total = header_size + c->size;
    uint8_t* buf = (uint8_t*)malloc(total);
    if (!buf) { *out_total = 0; return nullptr; }

    size_t off = 0;
    uint32_t magic = DDS_MAGIC;
    memcpy(buf + off, &magic, 4); off += 4;
    memcpy(buf + off, &hdr, sizeof(DDS_HEADER)); off += sizeof(DDS_HEADER);
    if (use_dx10) {
        memcpy(buf + off, &dx10, sizeof(DDS_HEADER_DXT10));
        off += sizeof(DDS_HEADER_DXT10);
    }
    memcpy(buf + off, c->data, c->size);
    *out_total = total;
    return buf;
}

TF_API int32_t tf_save_dds(const TfCompressed* c, const wchar_t* path) {
    if (!c) return -1;
    size_t total = 0;
    uint8_t* file_data = build_dds_file(c, &total);
    if (!file_data) return -2;
    bool ok = write_file(path, file_data, total);
    free(file_data);
    return ok ? 0 : -3;
}

TF_API int32_t tf_save_dds_memory(const TfCompressed* c,
                                   uint8_t** out_buf, size_t* out_size) {
    if (!c || !out_buf || !out_size) return -1;
    *out_buf = build_dds_file(c, out_size);
    return *out_buf ? 0 : -2;
}

TF_API TfCompressed* tf_load_dds(const wchar_t* path) {
    size_t file_size = 0;
    uint8_t* file_data = read_file(path, &file_size);
    if (!file_data || file_size < 128) { free(file_data); return nullptr; }

    uint32_t magic;
    memcpy(&magic, file_data, 4);
    if (magic != DDS_MAGIC) { free(file_data); return nullptr; }

    DDS_HEADER hdr;
    memcpy(&hdr, file_data + 4, sizeof(DDS_HEADER));

    int bc_fmt = -1;
    size_t pixel_offset = 4 + sizeof(DDS_HEADER);

    if (hdr.ddspf.flags & DDPF_FOURCC) {
        int mapped = fourcc_to_bc(hdr.ddspf.fourCC);
        if (mapped == -2) {
            // DX10 extended header
            if (file_size < pixel_offset + sizeof(DDS_HEADER_DXT10)) {
                free(file_data); return nullptr;
            }
            DDS_HEADER_DXT10 dx10;
            memcpy(&dx10, file_data + pixel_offset, sizeof(DDS_HEADER_DXT10));
            pixel_offset += sizeof(DDS_HEADER_DXT10);
            bc_fmt = dxgi_to_fmt(dx10.dxgiFormat);
        } else {
            bc_fmt = mapped;
        }
    } else if ((hdr.ddspf.flags & DDPF_RGB) && hdr.ddspf.rgbBitCount == 32) {
        // Uncompressed 32-bit BGRA/RGBA
        bc_fmt = TF_A8R8G8B8;
    }

    if (bc_fmt < 0) { free(file_data); return nullptr; }

    int w = (int)hdr.width;
    int h = (int)hdr.height;
    int mip_count = (hdr.flags & DDSD_MIPMAPCOUNT) ? (int)hdr.mipMapCount : 1;
    if (mip_count < 1) mip_count = 1;

    TfBCFormat fmt = (TfBCFormat)bc_fmt;

    // Calculate sizes
    size_t total = 0;
    size_t* offsets = (size_t*)malloc(mip_count * sizeof(size_t));
    size_t* sizes_arr = (size_t*)malloc(mip_count * sizeof(size_t));
    int mw = w, mh = h;
    for (int i = 0; i < mip_count; i++) {
        offsets[i] = total;
        sizes_arr[i] = calc_mip_size(mw, mh, fmt);
        total += sizes_arr[i];
        mw = (mw > 1) ? mw / 2 : 1;
        mh = (mh > 1) ? mh / 2 : 1;
    }

    size_t avail = file_size - pixel_offset;
    if (avail < total) { total = avail; } // clamp

    uint8_t* data = (uint8_t*)malloc(total);
    memcpy(data, file_data + pixel_offset, total);
    free(file_data);

    auto* result = new TfCompressed();
    result->data = data;
    result->size = total;
    result->width = w;
    result->height = h;
    result->format = bc_fmt;
    result->mip_count = mip_count;
    result->mip_offsets = offsets;
    result->mip_sizes = sizes_arr;
    return result;
}

// ── Utility: free a malloc'd buffer ──────────────────────────────────────────

TF_API void tf_free_buffer(void* buf) {
    free(buf);
}

// ── DLL entry ────────────────────────────────────────────────────────────────

BOOL APIENTRY DllMain(HMODULE, DWORD, LPVOID) { return TRUE; }
