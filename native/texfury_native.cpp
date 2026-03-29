/**
 * texfury_native.cpp
 *
 * C-API wrapper around stb_image, stb_image_resize2, and bc7enc_rdo
 * for Python ctypes consumption.
 *
 * Compression uses rdo_bc_encoder (whole-image, multithreaded).
 * DDS writing uses bc7enc_rdo's save_dds (from utils.h).
 * Decompression and DDS reading are handled locally.
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

// ── bc7enc_rdo ──────────────────────────────────────────────────────────────
#define SUPPORT_BC7E 1
#include "rdo_bc_encoder.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
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
// Values MUST match Python BCFormat IntEnum exactly.
enum TfBCFormat {
    // ABI-locked (0-5) — used by rdo_bc_encoder
    TF_BC1 = 0,
    TF_BC3 = 1,
    TF_BC4 = 2,
    TF_BC5 = 3,
    TF_BC7 = 4,
    TF_A8R8G8B8 = 5,     // Uncompressed 32-bit BGRA
    // New block-compressed (not supported by rdo_bc_encoder)
    TF_BC2 = 6,
    TF_BC6H = 7,
    // Uncompressed — 32-bit
    TF_R8G8B8A8 = 10,
    TF_B5G6R5 = 11,
    TF_B5G5R5A1 = 12,
    TF_R10G10B10A2 = 13,
    // Uncompressed — small
    TF_R8 = 20,
    TF_A8 = 21,
    TF_R8G8 = 22,
    // Uncompressed — float/HDR
    TF_R16_FLOAT = 30,
    TF_R16G16_FLOAT = 31,
    TF_R16G16B16A16_FLOAT = 32,
    TF_R32_FLOAT = 33,
    TF_R32G32B32A32_FLOAT = 34,
};

enum TfMipFilter {
    TF_FILTER_BOX          = 0,
    TF_FILTER_TRIANGLE     = 1,
    TF_FILTER_CUBICBSPLINE = 2,
    TF_FILTER_CATMULLROM   = 3,
    TF_FILTER_MITCHELL     = 4,
    TF_FILTER_POINT        = 5,
};

static stbir_filter tf_to_stbir_filter(int filter) {
    switch (filter) {
        case TF_FILTER_BOX:          return STBIR_FILTER_BOX;
        case TF_FILTER_TRIANGLE:     return STBIR_FILTER_TRIANGLE;
        case TF_FILTER_CUBICBSPLINE: return STBIR_FILTER_CUBICBSPLINE;
        case TF_FILTER_CATMULLROM:   return STBIR_FILTER_CATMULLROM;
        case TF_FILTER_MITCHELL:     return STBIR_FILTER_MITCHELL;
        case TF_FILTER_POINT:        return STBIR_FILTER_POINT_SAMPLE;
        default:                     return STBIR_FILTER_MITCHELL;
    }
}

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
    switch (fmt) {
        case TF_BC1: case TF_BC2: case TF_BC3:
        case TF_BC4: case TF_BC5: case TF_BC6H: case TF_BC7:
            return true;
        default:
            return false;
    }
}

static int block_byte_size(TfBCFormat fmt) {
    switch (fmt) {
        case TF_BC1: case TF_BC4: return 8;
        default: return 16; // BC2, BC3, BC5, BC6H, BC7
    }
}

static int pixel_byte_size(TfBCFormat fmt) {
    switch (fmt) {
        case TF_A8R8G8B8: case TF_R8G8B8A8: case TF_R10G10B10A2:
        case TF_R16G16_FLOAT: case TF_R32_FLOAT:
            return 4;
        case TF_B5G6R5: case TF_B5G5R5A1: case TF_R8G8:
        case TF_R16_FLOAT:
            return 2;
        case TF_R8: case TF_A8:
            return 1;
        case TF_R16G16B16A16_FLOAT:
            return 8;
        case TF_R32G32B32A32_FLOAT:
            return 16;
        default:
            return 4;
    }
}

static size_t calc_mip_size(int w, int h, TfBCFormat fmt) {
    if (is_block_compressed(fmt)) {
        int bw = (w + 3) / 4;
        int bh = (h + 3) / 4;
        if (bw < 1) bw = 1;
        if (bh < 1) bh = 1;
        return (size_t)bw * bh * block_byte_size(fmt);
    }
    return (size_t)w * h * pixel_byte_size(fmt);
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

// Map TfBCFormat → DXGI_FORMAT
static DXGI_FORMAT tf_to_dxgi(TfBCFormat fmt) {
    switch (fmt) {
        case TF_BC1: return DXGI_FORMAT_BC1_UNORM;
        case TF_BC2: return DXGI_FORMAT_BC2_UNORM;
        case TF_BC3: return DXGI_FORMAT_BC3_UNORM;
        case TF_BC4: return DXGI_FORMAT_BC4_UNORM;
        case TF_BC5: return DXGI_FORMAT_BC5_UNORM;
        case TF_BC6H: return DXGI_FORMAT_BC6H_UF16;
        case TF_BC7: return DXGI_FORMAT_BC7_UNORM;
        case TF_A8R8G8B8: return DXGI_FORMAT_B8G8R8A8_UNORM;
        case TF_R8G8B8A8: return DXGI_FORMAT_R8G8B8A8_UNORM;
        case TF_B5G6R5: return (DXGI_FORMAT)85;   // DXGI_FORMAT_B5G6R5_UNORM
        case TF_B5G5R5A1: return (DXGI_FORMAT)86;  // DXGI_FORMAT_B5G5R5A1_UNORM
        case TF_R10G10B10A2: return (DXGI_FORMAT)24; // DXGI_FORMAT_R10G10B10A2_UNORM
        case TF_R8: return (DXGI_FORMAT)61;         // DXGI_FORMAT_R8_UNORM
        case TF_A8: return (DXGI_FORMAT)65;         // DXGI_FORMAT_A8_UNORM
        case TF_R8G8: return (DXGI_FORMAT)49;       // DXGI_FORMAT_R8G8_UNORM
        case TF_R16_FLOAT: return (DXGI_FORMAT)54;  // DXGI_FORMAT_R16_FLOAT
        case TF_R16G16_FLOAT: return (DXGI_FORMAT)34; // DXGI_FORMAT_R16G16_FLOAT
        case TF_R16G16B16A16_FLOAT: return (DXGI_FORMAT)10; // DXGI_FORMAT_R16G16B16A16_FLOAT
        case TF_R32_FLOAT: return (DXGI_FORMAT)41;  // DXGI_FORMAT_R32_FLOAT
        case TF_R32G32B32A32_FLOAT: return (DXGI_FORMAT)2; // DXGI_FORMAT_R32G32B32A32_FLOAT
        default: return DXGI_FORMAT_UNKNOWN;
    }
}

// Map DXGI_FORMAT → TfBCFormat for DDS loading
static int dxgi_to_tf(uint32_t dxgi) {
    switch (dxgi) {
        case DXGI_FORMAT_BC1_UNORM: return TF_BC1;
        case 72: /* BC1_UNORM_SRGB */ return TF_BC1;
        case DXGI_FORMAT_BC2_UNORM: return TF_BC2;
        case 75: /* BC2_UNORM_SRGB */ return TF_BC2;
        case DXGI_FORMAT_BC3_UNORM: return TF_BC3;
        case 78: /* BC3_UNORM_SRGB */ return TF_BC3;
        case DXGI_FORMAT_BC4_UNORM: return TF_BC4;
        case DXGI_FORMAT_BC5_UNORM: return TF_BC5;
        case 95: /* BC6H_UF16 */ return TF_BC6H;
        case DXGI_FORMAT_BC7_UNORM: return TF_BC7;
        case 99: /* BC7_UNORM_SRGB */ return TF_BC7;
        case DXGI_FORMAT_B8G8R8A8_UNORM: return TF_A8R8G8B8;
        case 91: /* B8G8R8A8_UNORM_SRGB */ return TF_A8R8G8B8;
        case DXGI_FORMAT_R8G8B8A8_UNORM: return TF_R8G8B8A8;
        case 29: /* R8G8B8A8_UNORM_SRGB */ return TF_R8G8B8A8;
        case 85: return TF_B5G6R5;
        case 86: return TF_B5G5R5A1;
        case 24: return TF_R10G10B10A2;
        case 61: return TF_R8;
        case 65: return TF_A8;
        case 49: return TF_R8G8;
        case 54: return TF_R16_FLOAT;
        case 34: return TF_R16G16_FLOAT;
        case 10: return TF_R16G16B16A16_FLOAT;
        case 41: return TF_R32_FLOAT;
        case 2:  return TF_R32G32B32A32_FLOAT;
        default: return -1;
    }
}

// FourCC mapping for legacy DDS
static int fourcc_to_tf(uint32_t fourcc) {
    if (fourcc == 0x31545844) return TF_BC1; // "DXT1"
    if (fourcc == 0x33545844) return TF_BC3; // "DXT3" → treat as BC3
    if (fourcc == 0x35545844) return TF_BC3; // "DXT5"
    if (fourcc == 0x31495441) return TF_BC4; // "ATI1"
    if (fourcc == 0x32495441) return TF_BC5; // "ATI2"
    if (fourcc == 0x30315844) return -2;     // "DX10" → use extended header
    return -1;
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

TF_API TfImage* tf_resize(const TfImage* img, int new_w, int new_h, int filter) {
    if (!img || !img->pixels || new_w <= 0 || new_h <= 0) return nullptr;

    uint8_t* out = (uint8_t*)malloc((size_t)new_w * new_h * 4);
    if (!out) return nullptr;

    stbir_filter stb_filter = tf_to_stbir_filter(filter);

    STBIR_RESIZE resize;
    stbir_resize_init(&resize,
                      img->pixels, img->width, img->height, 0,
                      out, new_w, new_h, 0,
                      STBIR_RGBA, STBIR_TYPE_UINT8_SRGB);
    stbir_set_filters(&resize, stb_filter, stb_filter);
    stbir_resize_extended(&resize);

    auto* r = new TfImage();
    r->pixels = out;
    r->width = new_w;
    r->height = new_h;
    r->channels = 4;
    r->owned = true;
    return r;
}

TF_API TfImage* tf_resize_to_pot(const TfImage* img, int filter) {
    if (!img) return nullptr;
    int pw = (int)next_pot((uint32_t)img->width);
    int ph = (int)next_pot((uint32_t)img->height);
    if (pw == img->width && ph == img->height) {
        return tf_create_image(img->width, img->height, img->pixels);
    }
    return tf_resize(img, pw, ph, filter);
}

// ── Half-float conversion ────────────────────────────────────────────────────

// IEEE 754 half-precision: 1 sign + 5 exponent + 10 mantissa
static uint16_t float_to_half(float f) {
    uint32_t x;
    memcpy(&x, &f, 4);
    uint32_t sign = (x >> 16) & 0x8000;
    int32_t  exp  = ((x >> 23) & 0xFF) - 127 + 15;
    uint32_t mant = x & 0x7FFFFF;
    if (exp <= 0) return (uint16_t)sign;          // underflow → ±0
    if (exp >= 31) return (uint16_t)(sign | 0x7C00); // overflow → ±inf
    return (uint16_t)(sign | (exp << 10) | (mant >> 13));
}

// ── Compression (uses rdo_bc_encoder) ────────────────────────────────────────

// Convert RGBA u8 pixels to the target uncompressed format.
// Returns malloc'd buffer and sets *out_size. Returns nullptr on unsupported fmt.
static uint8_t* convert_pixels(const uint8_t* rgba, int w, int h,
                                TfBCFormat fmt, size_t* out_size) {
    size_t px = (size_t)w * h;
    size_t bpp = pixel_byte_size(fmt);
    size_t sz = px * bpp;
    uint8_t* dst = (uint8_t*)malloc(sz);
    if (!dst) return nullptr;

    switch (fmt) {
    case TF_A8R8G8B8:
        // RGBA → BGRA
        for (size_t i = 0; i < px; i++) {
            dst[i*4+0] = rgba[i*4+2];
            dst[i*4+1] = rgba[i*4+1];
            dst[i*4+2] = rgba[i*4+0];
            dst[i*4+3] = rgba[i*4+3];
        }
        break;
    case TF_R8G8B8A8:
        memcpy(dst, rgba, sz);
        break;
    case TF_B5G6R5:
        for (size_t i = 0; i < px; i++) {
            uint16_t r = rgba[i*4+0] >> 3;
            uint16_t g = rgba[i*4+1] >> 2;
            uint16_t b = rgba[i*4+2] >> 3;
            uint16_t v = (b) | (g << 5) | (r << 11);
            memcpy(dst + i*2, &v, 2);
        }
        break;
    case TF_B5G5R5A1:
        for (size_t i = 0; i < px; i++) {
            uint16_t r = rgba[i*4+0] >> 3;
            uint16_t g = rgba[i*4+1] >> 3;
            uint16_t b = rgba[i*4+2] >> 3;
            uint16_t a = rgba[i*4+3] >= 128 ? 1 : 0;
            uint16_t v = (b) | (g << 5) | (r << 10) | (a << 15);
            memcpy(dst + i*2, &v, 2);
        }
        break;
    case TF_R10G10B10A2:
        for (size_t i = 0; i < px; i++) {
            uint32_t r = (uint32_t)rgba[i*4+0] * 1023 / 255;
            uint32_t g = (uint32_t)rgba[i*4+1] * 1023 / 255;
            uint32_t b = (uint32_t)rgba[i*4+2] * 1023 / 255;
            uint32_t a = (uint32_t)rgba[i*4+3] * 3 / 255;
            uint32_t v = r | (g << 10) | (b << 20) | (a << 30);
            memcpy(dst + i*4, &v, 4);
        }
        break;
    case TF_R8:
        for (size_t i = 0; i < px; i++)
            dst[i] = rgba[i*4+0];
        break;
    case TF_A8:
        for (size_t i = 0; i < px; i++)
            dst[i] = rgba[i*4+3];
        break;
    case TF_R8G8:
        for (size_t i = 0; i < px; i++) {
            dst[i*2+0] = rgba[i*4+0];
            dst[i*2+1] = rgba[i*4+1];
        }
        break;
    case TF_R16_FLOAT:
        for (size_t i = 0; i < px; i++) {
            uint16_t v = float_to_half(rgba[i*4+0] / 255.0f);
            memcpy(dst + i*2, &v, 2);
        }
        break;
    case TF_R16G16_FLOAT:
        for (size_t i = 0; i < px; i++) {
            uint16_t r = float_to_half(rgba[i*4+0] / 255.0f);
            uint16_t g = float_to_half(rgba[i*4+1] / 255.0f);
            memcpy(dst + i*4, &r, 2);
            memcpy(dst + i*4+2, &g, 2);
        }
        break;
    case TF_R16G16B16A16_FLOAT:
        for (size_t i = 0; i < px; i++) {
            uint16_t ch[4];
            for (int c = 0; c < 4; c++)
                ch[c] = float_to_half(rgba[i*4+c] / 255.0f);
            memcpy(dst + i*8, ch, 8);
        }
        break;
    case TF_R32_FLOAT:
        for (size_t i = 0; i < px; i++) {
            float v = rgba[i*4+0] / 255.0f;
            memcpy(dst + i*4, &v, 4);
        }
        break;
    case TF_R32G32B32A32_FLOAT:
        for (size_t i = 0; i < px; i++) {
            float ch[4];
            for (int c = 0; c < 4; c++)
                ch[c] = rgba[i*4+c] / 255.0f;
            memcpy(dst + i*16, ch, 16);
        }
        break;
    default:
        free(dst);
        return nullptr;
    }
    *out_size = sz;
    return dst;
}

// Compress/convert a single mip level.
// For BC formats: uses rdo_bc_encoder. For uncompressed: pixel conversion.
// Returns malloc'd data and sets *out_size.
static uint8_t* compress_mip(const uint8_t* rgba, int w, int h,
                              TfBCFormat fmt, float quality,
                              size_t* out_size) {
    // Uncompressed formats: pixel conversion
    if (!is_block_compressed(fmt)) {
        return convert_pixels(rgba, w, h, fmt, out_size);
    }

    // BC2/BC6H not supported by rdo_bc_encoder
    if (fmt == TF_BC2 || fmt == TF_BC6H) return nullptr;

    // Build image_u8 from RGBA pixels
    utils::image_u8 src_img(w, h);
    memcpy(src_img.get_pixels().data(), rgba, (size_t)w * h * 4);

    // Configure encoder params
    rdo_bc::rdo_bc_params rp;
    rp.m_dxgi_format = tf_to_dxgi(fmt);
    rp.m_rdo_lambda = 0.0f;  // no RDO — just plain compression
    rp.m_status_output = false;
    rp.m_use_bc7e = true;
    rp.m_bc1_quality_level = (int)(quality * rgbcx::MAX_LEVEL);
    rp.m_bc7_uber_level = (int)(quality * 6.0f);
    if (rp.m_bc1_quality_level > (int)rgbcx::MAX_LEVEL)
        rp.m_bc1_quality_level = rgbcx::MAX_LEVEL;
    if (rp.m_bc7_uber_level > 6) rp.m_bc7_uber_level = 6;

    rdo_bc::rdo_bc_encoder encoder;
    if (!encoder.init(src_img, rp)) return nullptr;
    if (!encoder.encode()) return nullptr;

    size_t block_data_size = encoder.get_total_blocks_size_in_bytes();
    uint8_t* result = (uint8_t*)malloc(block_data_size);
    if (!result) return nullptr;
    memcpy(result, encoder.get_blocks(), block_data_size);
    *out_size = block_data_size;
    return result;
}

TF_API TfCompressed* tf_compress(const TfImage* img, int format,
                                  int generate_mipmaps, int min_mip_dim,
                                  float quality, int mip_filter) {
    if (!img || !img->pixels) return nullptr;
    ensure_init();

    TfBCFormat fmt = (TfBCFormat)format;
    int w = img->width;
    int h = img->height;

    // Calculate mip count
    int mip_count = 1;
    if (generate_mipmaps) {
        int min_d = (min_mip_dim > 0) ? min_mip_dim : 4;
        mip_count = calc_mip_count(w, h, min_d);
    }

    // Compress each mip level
    uint8_t** mip_datas = (uint8_t**)calloc(mip_count, sizeof(uint8_t*));
    size_t* sizes = (size_t*)malloc(mip_count * sizeof(size_t));
    if (!mip_datas || !sizes) { free(mip_datas); free(sizes); return nullptr; }

    uint8_t* resized_buf = nullptr;
    int mw = w, mh = h;

    for (int mip = 0; mip < mip_count; mip++) {
        const uint8_t* src = img->pixels;

        if (mip > 0) {
            // Downsample from original for better quality
            if (resized_buf) free(resized_buf);
            resized_buf = (uint8_t*)malloc((size_t)mw * mh * 4);

            stbir_filter stb_filt = tf_to_stbir_filter(mip_filter);
            STBIR_RESIZE rs;
            stbir_resize_init(&rs,
                              img->pixels, w, h, 0,
                              resized_buf, mw, mh, 0,
                              STBIR_RGBA, STBIR_TYPE_UINT8_SRGB);
            stbir_set_filters(&rs, stb_filt, stb_filt);
            stbir_resize_extended(&rs);

            src = resized_buf;
        }

        mip_datas[mip] = compress_mip(src, mw, mh, fmt, quality, &sizes[mip]);
        if (!mip_datas[mip]) {
            // Cleanup on failure
            for (int j = 0; j < mip; j++) free(mip_datas[j]);
            free(mip_datas); free(sizes); free(resized_buf);
            return nullptr;
        }

        mw = (mw > 1) ? mw / 2 : 1;
        mh = (mh > 1) ? mh / 2 : 1;
    }
    if (resized_buf) free(resized_buf);

    // Concatenate all mip data into one buffer
    size_t total_size = 0;
    size_t* offsets = (size_t*)malloc(mip_count * sizeof(size_t));
    for (int i = 0; i < mip_count; i++) {
        offsets[i] = total_size;
        total_size += sizes[i];
    }

    uint8_t* all_data = (uint8_t*)malloc(total_size);
    for (int i = 0; i < mip_count; i++) {
        memcpy(all_data + offsets[i], mip_datas[i], sizes[i]);
        free(mip_datas[i]);
    }
    free(mip_datas);

    auto* result = new TfCompressed();
    result->data = all_data;
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

// DDS writing uses bc7enc_rdo's save_dds for BC formats.
// For uncompressed (A8R8G8B8) we build the header ourselves.

// (dxgi_pixel_format_bpp removed — replaced by pixel_byte_size / block_byte_size)

// Build DDS in memory — we need this for the Python API since save_dds writes to disk.
// For BC formats, we use bc7enc_rdo's header logic via save_dds to a temp file,
// but it's cleaner to just build the header ourselves for consistency.
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

struct DDS_PIXELFORMAT_LOCAL {
    uint32_t size;
    uint32_t flags;
    uint32_t fourCC;
    uint32_t rgbBitCount;
    uint32_t rBitMask, gBitMask, bBitMask, aBitMask;
};

struct DDS_HEADER_LOCAL {
    uint32_t size;
    uint32_t flags;
    uint32_t height;
    uint32_t width;
    uint32_t pitchOrLinearSize;
    uint32_t depth;
    uint32_t mipMapCount;
    uint32_t reserved1[11];
    DDS_PIXELFORMAT_LOCAL ddspf;
    uint32_t caps;
    uint32_t caps2;
    uint32_t caps3;
    uint32_t caps4;
    uint32_t reserved2;
};

struct DDS_HEADER_DXT10_LOCAL {
    uint32_t dxgiFormat;
    uint32_t resourceDimension;
    uint32_t miscFlag;
    uint32_t arraySize;
    uint32_t miscFlags2;
};

static uint8_t* build_dds_file(const TfCompressed* c, size_t* out_total) {
    TfBCFormat fmt = (TfBCFormat)c->format;
    bool bc = is_block_compressed(fmt);

    // Legacy FourCC works for BC1 (DXT1), BC2 (DXT3), BC3 (DXT5).
    // Legacy pixel format works for A8R8G8B8 (32-bit BGRA).
    // Everything else needs DX10 extended header.
    bool legacy_fourcc = (fmt == TF_BC1 || fmt == TF_BC2 || fmt == TF_BC3);
    bool legacy_a8r8g8b8 = (fmt == TF_A8R8G8B8);
    bool use_dx10 = !legacy_fourcc && !legacy_a8r8g8b8;

    DDS_HEADER_LOCAL hdr = {};
    hdr.size = 124;
    hdr.height = c->height;
    hdr.width = c->width;
    hdr.depth = 1;
    hdr.caps = DDSCAPS_TEXTURE;
    hdr.ddspf.size = 32;

    if (legacy_a8r8g8b8) {
        hdr.flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_PITCH;
        hdr.pitchOrLinearSize = c->width * 4;
        hdr.ddspf.flags = DDPF_RGB | DDPF_ALPHAPIXELS;
        hdr.ddspf.rgbBitCount = 32;
        hdr.ddspf.rBitMask = 0x00FF0000;
        hdr.ddspf.gBitMask = 0x0000FF00;
        hdr.ddspf.bBitMask = 0x000000FF;
        hdr.ddspf.aBitMask = 0xFF000000;
    } else if (bc) {
        hdr.flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_LINEARSIZE;
        hdr.pitchOrLinearSize = (uint32_t)c->mip_sizes[0];
        hdr.ddspf.flags = DDPF_FOURCC;
        if (use_dx10) {
            hdr.ddspf.fourCC = 0x30315844; // "DX10"
        } else if (fmt == TF_BC1) {
            hdr.ddspf.fourCC = 0x31545844; // "DXT1"
        } else if (fmt == TF_BC2) {
            hdr.ddspf.fourCC = 0x33545844; // "DXT3"
        } else {
            hdr.ddspf.fourCC = 0x35545844; // "DXT5"
        }
    } else {
        // All other uncompressed formats → DX10
        hdr.flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_PITCH;
        hdr.pitchOrLinearSize = c->width * pixel_byte_size(fmt);
        hdr.ddspf.flags = DDPF_FOURCC;
        hdr.ddspf.fourCC = 0x30315844; // "DX10"
    }

    if (c->mip_count > 1) {
        hdr.flags |= DDSD_MIPMAPCOUNT;
        hdr.mipMapCount = c->mip_count;
        hdr.caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP;
    }

    DDS_HEADER_DXT10_LOCAL dx10 = {};
    if (use_dx10) {
        dx10.dxgiFormat = (uint32_t)tf_to_dxgi(fmt);
        dx10.resourceDimension = 3;
        dx10.arraySize = 1;
    }

    size_t header_size = 4 + sizeof(DDS_HEADER_LOCAL) + (use_dx10 ? sizeof(DDS_HEADER_DXT10_LOCAL) : 0);
    size_t total = header_size + c->size;
    uint8_t* buf = (uint8_t*)malloc(total);
    if (!buf) { *out_total = 0; return nullptr; }

    size_t off = 0;
    uint32_t magic = DDS_MAGIC;
    memcpy(buf + off, &magic, 4); off += 4;
    memcpy(buf + off, &hdr, sizeof(DDS_HEADER_LOCAL)); off += sizeof(DDS_HEADER_LOCAL);
    if (use_dx10) {
        memcpy(buf + off, &dx10, sizeof(DDS_HEADER_DXT10_LOCAL));
        off += sizeof(DDS_HEADER_DXT10_LOCAL);
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

// Parse DDS from a memory buffer. The buffer is NOT freed by this function.
static TfCompressed* parse_dds_buffer(const uint8_t* file_data, size_t file_size) {
    if (!file_data || file_size < 128) return nullptr;

    uint32_t magic;
    memcpy(&magic, file_data, 4);
    if (magic != DDS_MAGIC) return nullptr;

    DDS_HEADER_LOCAL hdr;
    memcpy(&hdr, file_data + 4, sizeof(DDS_HEADER_LOCAL));

    int bc_fmt = -1;
    size_t pixel_offset = 4 + sizeof(DDS_HEADER_LOCAL);

    if (hdr.ddspf.flags & DDPF_FOURCC) {
        int mapped = fourcc_to_tf(hdr.ddspf.fourCC);
        if (mapped == -2) {
            if (file_size < pixel_offset + sizeof(DDS_HEADER_DXT10_LOCAL))
                return nullptr;
            DDS_HEADER_DXT10_LOCAL dx10;
            memcpy(&dx10, file_data + pixel_offset, sizeof(DDS_HEADER_DXT10_LOCAL));
            pixel_offset += sizeof(DDS_HEADER_DXT10_LOCAL);
            bc_fmt = dxgi_to_tf(dx10.dxgiFormat);
        } else {
            bc_fmt = mapped;
        }
    } else if ((hdr.ddspf.flags & DDPF_RGB) && hdr.ddspf.rgbBitCount == 32) {
        bc_fmt = TF_A8R8G8B8;
    }

    if (bc_fmt < 0) return nullptr;

    int w = (int)hdr.width;
    int h = (int)hdr.height;
    int mip_count = (hdr.flags & DDSD_MIPMAPCOUNT) ? (int)hdr.mipMapCount : 1;
    if (mip_count < 1) mip_count = 1;

    TfBCFormat tfmt = (TfBCFormat)bc_fmt;

    size_t total = 0;
    size_t* offsets = (size_t*)malloc(mip_count * sizeof(size_t));
    size_t* sizes_arr = (size_t*)malloc(mip_count * sizeof(size_t));
    int mw = w, mh = h;
    for (int i = 0; i < mip_count; i++) {
        offsets[i] = total;
        sizes_arr[i] = calc_mip_size(mw, mh, tfmt);
        total += sizes_arr[i];
        mw = (mw > 1) ? mw / 2 : 1;
        mh = (mh > 1) ? mh / 2 : 1;
    }

    size_t avail = file_size - pixel_offset;
    if (avail < total) { total = avail; }

    uint8_t* data = (uint8_t*)malloc(total);
    memcpy(data, file_data + pixel_offset, total);

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

TF_API TfCompressed* tf_load_dds(const wchar_t* path) {
    size_t file_size = 0;
    uint8_t* file_data = read_file(path, &file_size);
    if (!file_data) return nullptr;
    TfCompressed* result = parse_dds_buffer(file_data, file_size);
    free(file_data);
    return result;
}

TF_API TfCompressed* tf_load_dds_memory(const uint8_t* data, size_t size) {
    return parse_dds_buffer(data, size);
}

// ── Block decompression ──────────────────────────────────────────────────────

// IEEE 754 half → float
static float half_to_float(uint16_t h) {
    uint32_t sign = (h >> 15) & 1;
    uint32_t exp  = (h >> 10) & 0x1F;
    uint32_t mant = h & 0x3FF;
    uint32_t f;
    if (exp == 0) {
        if (mant == 0) f = sign << 31;
        else { // denorm
            float val = (float)mant / 1024.0f;
            val = val * (1.0f / 16384.0f); // 2^-14
            if (sign) val = -val;
            memcpy(&f, &val, 4);
            return val;
        }
    } else if (exp == 31) {
        f = (sign << 31) | 0x7F800000 | (mant << 13);
    } else {
        f = (sign << 31) | ((exp - 15 + 127) << 23) | (mant << 13);
    }
    float result;
    memcpy(&result, &f, 4);
    return result;
}

static uint8_t float_to_u8(float f) {
    int v = (int)(f * 255.0f + 0.5f);
    if (v < 0) return 0;
    if (v > 255) return 255;
    return (uint8_t)v;
}

static uint8_t* decompress_mip(const uint8_t* src, int w, int h, TfBCFormat fmt) {
    size_t px_count = (size_t)w * h;
    uint8_t* rgba = (uint8_t*)malloc(px_count * 4);
    if (!rgba) return nullptr;

    // Handle all uncompressed formats
    if (!is_block_compressed(fmt)) {
        switch (fmt) {
        case TF_A8R8G8B8:
            for (size_t p = 0; p < px_count; p++) {
                rgba[p*4+0] = src[p*4+2];
                rgba[p*4+1] = src[p*4+1];
                rgba[p*4+2] = src[p*4+0];
                rgba[p*4+3] = src[p*4+3];
            }
            break;
        case TF_R8G8B8A8:
            memcpy(rgba, src, px_count * 4);
            break;
        case TF_B5G6R5:
            for (size_t p = 0; p < px_count; p++) {
                uint16_t v; memcpy(&v, src + p*2, 2);
                rgba[p*4+0] = (uint8_t)(((v >> 11) & 0x1F) * 255 / 31);
                rgba[p*4+1] = (uint8_t)(((v >> 5) & 0x3F) * 255 / 63);
                rgba[p*4+2] = (uint8_t)((v & 0x1F) * 255 / 31);
                rgba[p*4+3] = 255;
            }
            break;
        case TF_B5G5R5A1:
            for (size_t p = 0; p < px_count; p++) {
                uint16_t v; memcpy(&v, src + p*2, 2);
                rgba[p*4+0] = (uint8_t)(((v >> 10) & 0x1F) * 255 / 31);
                rgba[p*4+1] = (uint8_t)(((v >> 5) & 0x1F) * 255 / 31);
                rgba[p*4+2] = (uint8_t)((v & 0x1F) * 255 / 31);
                rgba[p*4+3] = (v >> 15) ? 255 : 0;
            }
            break;
        case TF_R10G10B10A2:
            for (size_t p = 0; p < px_count; p++) {
                uint32_t v; memcpy(&v, src + p*4, 4);
                rgba[p*4+0] = (uint8_t)((v & 0x3FF) * 255 / 1023);
                rgba[p*4+1] = (uint8_t)(((v >> 10) & 0x3FF) * 255 / 1023);
                rgba[p*4+2] = (uint8_t)(((v >> 20) & 0x3FF) * 255 / 1023);
                rgba[p*4+3] = (uint8_t)(((v >> 30) & 0x3) * 255 / 3);
            }
            break;
        case TF_R8:
            for (size_t p = 0; p < px_count; p++) {
                rgba[p*4+0] = src[p];
                rgba[p*4+1] = src[p];
                rgba[p*4+2] = src[p];
                rgba[p*4+3] = 255;
            }
            break;
        case TF_A8:
            for (size_t p = 0; p < px_count; p++) {
                rgba[p*4+0] = 255;
                rgba[p*4+1] = 255;
                rgba[p*4+2] = 255;
                rgba[p*4+3] = src[p];
            }
            break;
        case TF_R8G8:
            for (size_t p = 0; p < px_count; p++) {
                rgba[p*4+0] = src[p*2+0];
                rgba[p*4+1] = src[p*2+1];
                rgba[p*4+2] = 0;
                rgba[p*4+3] = 255;
            }
            break;
        case TF_R16_FLOAT:
            for (size_t p = 0; p < px_count; p++) {
                uint16_t v; memcpy(&v, src + p*2, 2);
                uint8_t u = float_to_u8(half_to_float(v));
                rgba[p*4+0] = u; rgba[p*4+1] = u; rgba[p*4+2] = u; rgba[p*4+3] = 255;
            }
            break;
        case TF_R16G16_FLOAT:
            for (size_t p = 0; p < px_count; p++) {
                uint16_t r, g; memcpy(&r, src+p*4, 2); memcpy(&g, src+p*4+2, 2);
                rgba[p*4+0] = float_to_u8(half_to_float(r));
                rgba[p*4+1] = float_to_u8(half_to_float(g));
                rgba[p*4+2] = 0; rgba[p*4+3] = 255;
            }
            break;
        case TF_R16G16B16A16_FLOAT:
            for (size_t p = 0; p < px_count; p++) {
                uint16_t ch[4]; memcpy(ch, src+p*8, 8);
                for (int c = 0; c < 4; c++)
                    rgba[p*4+c] = float_to_u8(half_to_float(ch[c]));
            }
            break;
        case TF_R32_FLOAT:
            for (size_t p = 0; p < px_count; p++) {
                float v; memcpy(&v, src+p*4, 4);
                uint8_t u = float_to_u8(v);
                rgba[p*4+0] = u; rgba[p*4+1] = u; rgba[p*4+2] = u; rgba[p*4+3] = 255;
            }
            break;
        case TF_R32G32B32A32_FLOAT:
            for (size_t p = 0; p < px_count; p++) {
                float ch[4]; memcpy(ch, src+p*16, 16);
                for (int c = 0; c < 4; c++)
                    rgba[p*4+c] = float_to_u8(ch[c]);
            }
            break;
        default:
            free(rgba);
            return nullptr;
        }
        return rgba;
    }

    int bw = (w + 3) / 4;
    int bh = (h + 3) / 4;
    int bsize = block_byte_size(fmt);

    uint8_t block_out[4 * 4 * 4]; // 16 pixels × 4 bytes

    for (int by = 0; by < bh; by++) {
        for (int bx = 0; bx < bw; bx++) {
            const uint8_t* block = src + ((size_t)by * bw + bx) * bsize;
            memset(block_out, 255, sizeof(block_out));

            switch (fmt) {
                case TF_BC1:
                    rgbcx::unpack_bc1(block, block_out, true);
                    break;
                case TF_BC3:
                    rgbcx::unpack_bc3(block, block_out);
                    break;
                case TF_BC4:
                    {
                        uint8_t r_vals[16];
                        rgbcx::unpack_bc4(block, r_vals, 1);
                        for (int i = 0; i < 16; i++) {
                            block_out[i * 4 + 0] = r_vals[i];
                            block_out[i * 4 + 1] = r_vals[i];
                            block_out[i * 4 + 2] = r_vals[i];
                            block_out[i * 4 + 3] = 255;
                        }
                    }
                    break;
                case TF_BC5:
                    {
                        uint8_t rg_vals[16 * 4];
                        memset(rg_vals, 0, sizeof(rg_vals));
                        for (int i = 0; i < 16; i++) rg_vals[i * 4 + 3] = 255;
                        rgbcx::unpack_bc5(block, rg_vals, 0, 1, 4);
                        memcpy(block_out, rg_vals, sizeof(block_out));
                    }
                    break;
                case TF_BC7:
                    bc7decomp::unpack_bc7(block, (bc7decomp::color_rgba*)block_out);
                    break;
                default:
                    break;
            }

            // Copy block pixels to output image
            for (int y = 0; y < 4; y++) {
                int py = by * 4 + y;
                if (py >= h) break;
                for (int x = 0; x < 4; x++) {
                    int px = bx * 4 + x;
                    if (px >= w) break;
                    memcpy(&rgba[(py * w + px) * 4],
                           &block_out[(y * 4 + x) * 4], 4);
                }
            }
        }
    }

    return rgba;
}

TF_API uint8_t* tf_decompress(const TfCompressed* c, int mip, int* out_w, int* out_h) {
    if (!c || mip < 0 || mip >= c->mip_count) return nullptr;

    int mw = c->width, mh = c->height;
    for (int i = 0; i < mip; i++) {
        mw = (mw > 1) ? mw / 2 : 1;
        mh = (mh > 1) ? mh / 2 : 1;
    }

    const uint8_t* src = c->data + c->mip_offsets[mip];
    uint8_t* out = decompress_mip(src, mw, mh, (TfBCFormat)c->format);
    if (out) {
        if (out_w) *out_w = mw;
        if (out_h) *out_h = mh;
    }
    return out;
}

// ── Quality metrics ──────────────────────────────────────────────────────────

TF_API double tf_psnr(const uint8_t* original, const uint8_t* compressed,
                       int width, int height, int channels) {
    if (!original || !compressed || width <= 0 || height <= 0) return 0.0;
    if (channels < 1) channels = 1;
    if (channels > 4) channels = 4;

    double mse = 0.0;
    size_t count = (size_t)width * height;
    for (size_t i = 0; i < count; i++) {
        for (int c = 0; c < channels; c++) {
            double diff = (double)original[i * 4 + c] - (double)compressed[i * 4 + c];
            mse += diff * diff;
        }
    }
    mse /= (double)(count * channels);
    if (mse < 1e-10) return 100.0;
    return 10.0 * log10(255.0 * 255.0 / mse);
}

TF_API double tf_ssim(const uint8_t* original, const uint8_t* compressed,
                       int width, int height) {
    if (!original || !compressed || width <= 0 || height <= 0) return 0.0;

    size_t count = (size_t)width * height;

    double mean_x = 0, mean_y = 0;
    for (size_t i = 0; i < count; i++) {
        double lx = 0.2126 * original[i * 4] + 0.7152 * original[i * 4 + 1] + 0.0722 * original[i * 4 + 2];
        double ly = 0.2126 * compressed[i * 4] + 0.7152 * compressed[i * 4 + 1] + 0.0722 * compressed[i * 4 + 2];
        mean_x += lx;
        mean_y += ly;
    }
    mean_x /= count;
    mean_y /= count;

    double var_x = 0, var_y = 0, cov_xy = 0;
    for (size_t i = 0; i < count; i++) {
        double lx = 0.2126 * original[i * 4] + 0.7152 * original[i * 4 + 1] + 0.0722 * original[i * 4 + 2];
        double ly = 0.2126 * compressed[i * 4] + 0.7152 * compressed[i * 4 + 1] + 0.0722 * compressed[i * 4 + 2];
        double dx = lx - mean_x;
        double dy = ly - mean_y;
        var_x += dx * dx;
        var_y += dy * dy;
        cov_xy += dx * dy;
    }
    var_x /= count;
    var_y /= count;
    cov_xy /= count;

    const double C1 = 6.5025;
    const double C2 = 58.5225;

    double num = (2.0 * mean_x * mean_y + C1) * (2.0 * cov_xy + C2);
    double den = (mean_x * mean_x + mean_y * mean_y + C1) * (var_x + var_y + C2);
    return num / den;
}

// ── Utility: free a malloc'd buffer ──────────────────────────────────────────

TF_API void tf_free_buffer(void* buf) {
    free(buf);
}

// ── DLL entry ────────────────────────────────────────────────────────────────
