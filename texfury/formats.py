"""DDS / BC compression format definitions."""

from enum import IntEnum


class RscCompression(IntEnum):
    """Compression algorithm for RSC (RAGE resource) containers."""

    DEFLATE = 1  # zlib raw deflate — used by GTA V Legacy, GTA V Enhanced
    OODLE = 2    # Oodle Kraken — used by RDR2 vanilla files


class BCFormat(IntEnum):
    """Texture formats — block-compressed and uncompressed.

    Values 0–5 match the native C library enum and MUST NOT change.
    """

    # Block-compressed formats (4x4 pixel blocks)
    # ⚠ Values 0-5 are ABI-locked to the native texfury_native.dll enum.
    BC1 = 0        # RGB, 8 bytes/block (aka DXT1). No alpha.
    BC3 = 1        # RGBA, 16 bytes/block (aka DXT5). Interpolated alpha.
    BC4 = 2        # Single channel (R), 8 bytes/block (aka ATI1).
    BC5 = 3        # Two channels (RG), 16 bytes/block (aka ATI2). Normal maps.
    BC7 = 4        # RGBA, 16 bytes/block. High quality, slower to encode.
    A8R8G8B8 = 5   # Uncompressed 32-bit BGRA (D3DFMT order).

    # New block-compressed formats (not handled by the native compressor)
    BC2 = 6        # RGBA, 16 bytes/block (aka DXT3). Explicit 4-bit alpha.
    BC6H = 7       # HDR RGB, 16 bytes/block. Half-float. Cubemaps/lightmaps.

    # Uncompressed — 32-bit
    R8G8B8A8 = 10  # 32-bit RGBA.
    B5G6R5 = 11    # 16-bit RGB 5-6-5.
    B5G5R5A1 = 12  # 16-bit BGRA 5-5-5-1.
    R10G10B10A2 = 13  # 32-bit RGB 10-10-10 + 2-bit alpha.

    # Uncompressed — small
    R8 = 20        # 8-bit single channel (luminance/height).
    A8 = 21        # 8-bit alpha only.
    R8G8 = 22      # 16-bit two channels.

    # Uncompressed — float/HDR
    R16_FLOAT = 30          # 16-bit half-float single channel.
    R16G16_FLOAT = 31       # 32-bit half-float two channels.
    R16G16B16A16_FLOAT = 32 # 64-bit half-float RGBA. HDR.
    R32_FLOAT = 33          # 32-bit float single channel.
    R32G32B32A32_FLOAT = 34 # 128-bit float RGBA. Full precision HDR.


# ── Block compression helpers ─────────────────────────────────────────────

_BLOCK_COMPRESSED = frozenset({
    BCFormat.BC1, BCFormat.BC2, BCFormat.BC3, BCFormat.BC4,
    BCFormat.BC5, BCFormat.BC6H, BCFormat.BC7,
})

# Bytes per 4x4 block for block-compressed formats.
_BLOCK_BYTES: dict[BCFormat, int] = {
    BCFormat.BC1: 8,
    BCFormat.BC2: 16,
    BCFormat.BC3: 16,
    BCFormat.BC4: 8,
    BCFormat.BC5: 16,
    BCFormat.BC6H: 16,
    BCFormat.BC7: 16,
}

# Bytes per pixel for uncompressed formats.
_PIXEL_BYTES: dict[BCFormat, int] = {
    BCFormat.A8R8G8B8: 4,
    BCFormat.R8G8B8A8: 4,
    BCFormat.R10G10B10A2: 4,
    BCFormat.B5G6R5: 2,
    BCFormat.B5G5R5A1: 2,
    BCFormat.R8: 1,
    BCFormat.A8: 1,
    BCFormat.R8G8: 2,
    BCFormat.R16_FLOAT: 2,
    BCFormat.R16G16_FLOAT: 4,
    BCFormat.R16G16B16A16_FLOAT: 8,
    BCFormat.R32_FLOAT: 4,
    BCFormat.R32G32B32A32_FLOAT: 16,
}


def is_block_compressed(fmt: BCFormat) -> bool:
    """Return True if the format uses block compression."""
    return fmt in _BLOCK_COMPRESSED


def block_byte_size(fmt: BCFormat) -> int:
    """Compressed block size in bytes (per 4x4 pixel block).

    Only valid for block-compressed formats.
    """
    return _BLOCK_BYTES[fmt]


def pixel_byte_size(fmt: BCFormat) -> int:
    """Bytes per pixel for uncompressed formats.

    Only valid for non-block-compressed formats.
    """
    return _PIXEL_BYTES[fmt]


def mip_data_size(width: int, height: int, fmt: BCFormat) -> int:
    """Data size in bytes for a single mip level."""
    if is_block_compressed(fmt):
        bw = max(1, (width + 3) // 4)
        bh = max(1, (height + 3) // 4)
        return bw * bh * _BLOCK_BYTES[fmt]
    return width * height * _PIXEL_BYTES[fmt]


def total_mip_data_size(width: int, height: int, fmt: BCFormat, levels: int) -> int:
    """Total data size across all mip levels."""
    total = 0
    w, h = width, height
    for _ in range(levels):
        total += mip_data_size(w, h, fmt)
        w = max(1, w // 2)
        h = max(1, h // 2)
    return total


def row_pitch(width: int, fmt: BCFormat) -> int:
    """Bytes per row (of blocks for BC, of pixels for uncompressed)."""
    if is_block_compressed(fmt):
        bw = max(1, (width + 3) // 4)
        return bw * _BLOCK_BYTES[fmt]
    return width * _PIXEL_BYTES[fmt]


# ── Mip filter ────────────────────────────────────────────────────────────

class MipFilter(IntEnum):
    """Downsampling filter for mipmap generation and image resizing."""

    BOX = 0           # Simple average. Fast, correct for exact 2:1 downscale.
    TRIANGLE = 1      # Bilinear interpolation.
    CUBIC_BSPLINE = 2 # Gaussian-like smoothing (B=1, C=0).
    CATMULL_ROM = 3   # Sharp cubic interpolation. Good for upscaling.
    MITCHELL = 4      # Balanced sharpness/smoothness (B=1/3, C=1/3). Best general-purpose.
    POINT = 5         # Nearest-neighbor. No interpolation.


# ── Format suggestion ─────────────────────────────────────────────────────

def suggest_format(has_alpha: bool, *, normal_map: bool = False,
                   single_channel: bool = False,
                   quality_over_size: bool = True) -> BCFormat:
    """Suggest the best BCFormat based on image characteristics.

    Parameters
    ----------
    has_alpha : bool
        Whether the image has meaningful transparency.
    normal_map : bool
        True if this is a normal map.
    single_channel : bool
        True if only one channel is meaningful (grayscale/height).
    quality_over_size : bool
        True prefers BC7 (better quality), False prefers BC1/BC3 (smaller).
    """
    if normal_map:
        return BCFormat.BC5
    if single_channel:
        return BCFormat.BC4
    if has_alpha:
        return BCFormat.BC7 if quality_over_size else BCFormat.BC3
    return BCFormat.BC7 if quality_over_size else BCFormat.BC1


# ── DXGI_FORMAT ───────────────────────────────────────────────────────────

class DXGIFormat(IntEnum):
    R32G32B32A32_FLOAT = 2
    R16G16B16A16_FLOAT = 10
    R10G10B10A2_UNORM = 24
    R8G8B8A8_UNORM = 28
    R16G16_FLOAT = 34
    R32_FLOAT = 41
    R8G8_UNORM = 49
    R16_FLOAT = 54
    R8_UNORM = 61
    A8_UNORM = 65
    BC1_UNORM = 71
    BC2_UNORM = 74
    BC3_UNORM = 77
    BC4_UNORM = 80
    BC5_UNORM = 83
    B5G6R5_UNORM = 85
    B5G5R5A1_UNORM = 86
    B8G8R8A8_UNORM = 87
    BC6H_UF16 = 95
    BC7_UNORM = 98

BC_TO_DXGI: dict[BCFormat, int] = {
    BCFormat.BC1: DXGIFormat.BC1_UNORM,
    BCFormat.BC2: DXGIFormat.BC2_UNORM,
    BCFormat.BC3: DXGIFormat.BC3_UNORM,
    BCFormat.BC4: DXGIFormat.BC4_UNORM,
    BCFormat.BC5: DXGIFormat.BC5_UNORM,
    BCFormat.BC6H: DXGIFormat.BC6H_UF16,
    BCFormat.BC7: DXGIFormat.BC7_UNORM,
    BCFormat.A8R8G8B8: DXGIFormat.B8G8R8A8_UNORM,
    BCFormat.R8G8B8A8: DXGIFormat.R8G8B8A8_UNORM,
    BCFormat.B5G6R5: DXGIFormat.B5G6R5_UNORM,
    BCFormat.B5G5R5A1: DXGIFormat.B5G5R5A1_UNORM,
    BCFormat.R10G10B10A2: DXGIFormat.R10G10B10A2_UNORM,
    BCFormat.R8: DXGIFormat.R8_UNORM,
    BCFormat.A8: DXGIFormat.A8_UNORM,
    BCFormat.R8G8: DXGIFormat.R8G8_UNORM,
    BCFormat.R16_FLOAT: DXGIFormat.R16_FLOAT,
    BCFormat.R16G16_FLOAT: DXGIFormat.R16G16_FLOAT,
    BCFormat.R16G16B16A16_FLOAT: DXGIFormat.R16G16B16A16_FLOAT,
    BCFormat.R32_FLOAT: DXGIFormat.R32_FLOAT,
    BCFormat.R32G32B32A32_FLOAT: DXGIFormat.R32G32B32A32_FLOAT,
}

DXGI_TO_BC: dict[int, BCFormat] = {v: k for k, v in BC_TO_DXGI.items()}


# ── FourCC codes (legacy DDS / DX9) ──────────────────────────────────────

FOURCC_DXT1 = 0x31545844
FOURCC_DXT3 = 0x33545844
FOURCC_DXT5 = 0x35545844
FOURCC_ATI1 = 0x31495441
FOURCC_ATI2 = 0x32495441
FOURCC_BC7 = 0x20374342   # "BC7 "
FOURCC_DX10 = 0x30315844  # "DX10" — signals DDS_HEADER_DXT10 extension

BC_TO_FOURCC: dict[BCFormat, int] = {
    BCFormat.BC1: FOURCC_DXT1,
    BCFormat.BC2: FOURCC_DXT3,
    BCFormat.BC3: FOURCC_DXT5,
    BCFormat.BC4: FOURCC_ATI1,
    BCFormat.BC5: FOURCC_ATI2,
}

FOURCC_TO_BC: dict[int, BCFormat] = {v: k for k, v in BC_TO_FOURCC.items()}


# ── DX9 format codes (YTD m_Format field) ────────────────────────────────

D3DFMT_A8R8G8B8 = 21
D3DFMT_A8 = 28
D3DFMT_A1R5G5B5 = 25
D3DFMT_R5G6B5 = 23
D3DFMT_L8 = 50

BC_TO_DX9: dict[BCFormat, int] = {
    BCFormat.BC1: FOURCC_DXT1,
    BCFormat.BC2: FOURCC_DXT3,
    BCFormat.BC3: FOURCC_DXT5,
    BCFormat.BC4: FOURCC_ATI1,
    BCFormat.BC5: FOURCC_ATI2,
    BCFormat.BC7: FOURCC_BC7,
    BCFormat.A8R8G8B8: D3DFMT_A8R8G8B8,
    BCFormat.A8: D3DFMT_A8,
    BCFormat.B5G5R5A1: D3DFMT_A1R5G5B5,
    BCFormat.B5G6R5: D3DFMT_R5G6B5,
    BCFormat.R8: D3DFMT_L8,
}

DX9_TO_BC: dict[int, BCFormat] = {v: k for k, v in BC_TO_DX9.items()}


# ── RSC8 texture format codes (DXGI values — GTA V Enhanced / RDR2) ──────

class Rsc8TextureFormat(IntEnum):
    # BC formats
    BC1_UNORM = 0x47
    BC1_UNORM_SRGB = 0x48
    BC2_UNORM = 0x4A
    BC2_UNORM_SRGB = 0x4B
    BC3_UNORM = 0x4D
    BC3_UNORM_SRGB = 0x4E
    BC4_UNORM = 0x50
    BC5_UNORM = 0x53
    BC6H_UF16 = 0x5F
    BC7_UNORM = 0x62
    BC7_UNORM_SRGB = 0x63
    # Uncompressed
    R8_UNORM = 0x3D
    A8_UNORM = 0x41
    R8G8_UNORM = 0x31
    R8G8B8A8_UNORM = 0x1C
    R8G8B8A8_UNORM_SRGB = 0x1D
    B8G8R8A8_UNORM = 0x57
    B8G8R8A8_UNORM_SRGB = 0x5B
    B5G6R5_UNORM = 0x55
    B5G5R5A1_UNORM = 0x56
    R10G10B10A2_UNORM = 0x18
    # Float
    R16_FLOAT = 0x36
    R16G16_FLOAT = 0x22
    R16G16B16A16_FLOAT = 0x0A
    R32_FLOAT = 0x29
    R32G32B32A32_FLOAT = 0x02

BC_TO_RSC8: dict[BCFormat, int] = {
    BCFormat.BC1: Rsc8TextureFormat.BC1_UNORM,
    BCFormat.BC2: Rsc8TextureFormat.BC2_UNORM,
    BCFormat.BC3: Rsc8TextureFormat.BC3_UNORM,
    BCFormat.BC4: Rsc8TextureFormat.BC4_UNORM,
    BCFormat.BC5: Rsc8TextureFormat.BC5_UNORM,
    BCFormat.BC6H: Rsc8TextureFormat.BC6H_UF16,
    BCFormat.BC7: Rsc8TextureFormat.BC7_UNORM,
    BCFormat.A8R8G8B8: Rsc8TextureFormat.B8G8R8A8_UNORM,
    BCFormat.R8G8B8A8: Rsc8TextureFormat.R8G8B8A8_UNORM,
    BCFormat.B5G6R5: Rsc8TextureFormat.B5G6R5_UNORM,
    BCFormat.B5G5R5A1: Rsc8TextureFormat.B5G5R5A1_UNORM,
    BCFormat.R10G10B10A2: Rsc8TextureFormat.R10G10B10A2_UNORM,
    BCFormat.R8: Rsc8TextureFormat.R8_UNORM,
    BCFormat.A8: Rsc8TextureFormat.A8_UNORM,
    BCFormat.R8G8: Rsc8TextureFormat.R8G8_UNORM,
    BCFormat.R16_FLOAT: Rsc8TextureFormat.R16_FLOAT,
    BCFormat.R16G16_FLOAT: Rsc8TextureFormat.R16G16_FLOAT,
    BCFormat.R16G16B16A16_FLOAT: Rsc8TextureFormat.R16G16B16A16_FLOAT,
    BCFormat.R32_FLOAT: Rsc8TextureFormat.R32_FLOAT,
    BCFormat.R32G32B32A32_FLOAT: Rsc8TextureFormat.R32G32B32A32_FLOAT,
}

RSC8_TO_BC: dict[int, BCFormat] = {v: k for k, v in BC_TO_RSC8.items()}

# SRGB variants map to the same BCFormat (same block encoding, different color space)
RSC8_TO_BC[Rsc8TextureFormat.BC1_UNORM_SRGB] = BCFormat.BC1
RSC8_TO_BC[Rsc8TextureFormat.BC2_UNORM_SRGB] = BCFormat.BC2
RSC8_TO_BC[Rsc8TextureFormat.BC3_UNORM_SRGB] = BCFormat.BC3
RSC8_TO_BC[Rsc8TextureFormat.BC7_UNORM_SRGB] = BCFormat.BC7
RSC8_TO_BC[Rsc8TextureFormat.R8G8B8A8_UNORM_SRGB] = BCFormat.R8G8B8A8
RSC8_TO_BC[Rsc8TextureFormat.B8G8R8A8_UNORM_SRGB] = BCFormat.A8R8G8B8


# ── RSC5 texture format codes (GTA IV WTD — FourCC / D3DFMT uint32) ──────

class Rsc5TextureFormat(IntEnum):
    DXT1 = 0x31545844
    DXT3 = 0x33545844
    DXT5 = 0x35545844
    A8R8G8B8 = 21
    A1R5G5B5 = 25
    R5G6B5 = 23
    A8 = 28
    L8 = 50

BC_TO_RSC5: dict[BCFormat, int] = {
    BCFormat.BC1: Rsc5TextureFormat.DXT1,
    BCFormat.BC2: Rsc5TextureFormat.DXT3,
    BCFormat.BC3: Rsc5TextureFormat.DXT5,
    BCFormat.A8R8G8B8: Rsc5TextureFormat.A8R8G8B8,
    BCFormat.B5G5R5A1: Rsc5TextureFormat.A1R5G5B5,
    BCFormat.B5G6R5: Rsc5TextureFormat.R5G6B5,
    BCFormat.A8: Rsc5TextureFormat.A8,
    BCFormat.R8: Rsc5TextureFormat.L8,
}

RSC5_TO_BC: dict[int, BCFormat] = {
    Rsc5TextureFormat.DXT1: BCFormat.BC1,
    Rsc5TextureFormat.DXT3: BCFormat.BC2,
    Rsc5TextureFormat.DXT5: BCFormat.BC3,
    Rsc5TextureFormat.A8R8G8B8: BCFormat.A8R8G8B8,
    Rsc5TextureFormat.A1R5G5B5: BCFormat.B5G5R5A1,
    Rsc5TextureFormat.R5G6B5: BCFormat.B5G6R5,
    Rsc5TextureFormat.A8: BCFormat.A8,
    Rsc5TextureFormat.L8: BCFormat.R8,
}

# Formats NOT supported by GTA IV
_GTA4_UNSUPPORTED = frozenset({
    BCFormat.BC4, BCFormat.BC5, BCFormat.BC6H, BCFormat.BC7,
    BCFormat.R8G8B8A8, BCFormat.R10G10B10A2,
    BCFormat.R8G8,
    BCFormat.R16_FLOAT, BCFormat.R16G16_FLOAT, BCFormat.R16G16B16A16_FLOAT,
    BCFormat.R32_FLOAT, BCFormat.R32G32B32A32_FLOAT,
})
