"""DDS / BC compression format definitions."""

from enum import IntEnum


class RscCompression(IntEnum):
    """Compression algorithm for RSC (RAGE resource) containers."""

    DEFLATE = 1  # zlib raw deflate — used by GTA V Legacy, GTA V Enhanced
    OODLE = 2    # Oodle Kraken — used by RDR2 vanilla files


class BCFormat(IntEnum):
    """Block compression formats for DDS textures."""

    BC1 = 0   # RGB, 6:1 compression (aka DXT1). No alpha.
    BC3 = 1   # RGBA, 4:1 compression (aka DXT5). Full alpha.
    BC4 = 2   # Single channel (R), 4:1 compression (aka ATI1).
    BC5 = 3   # Two channels (RG), 4:1 compression (aka ATI2). Normal maps.
    BC7 = 4   # RGBA, 4:1 compression. High quality, slower to encode.
    A8R8G8B8 = 5  # Uncompressed 32-bit BGRA.


class MipFilter(IntEnum):
    """Downsampling filter for mipmap generation and image resizing."""

    BOX = 0           # Simple average. Fast, correct for exact 2:1 downscale.
    TRIANGLE = 1      # Bilinear interpolation.
    CUBIC_BSPLINE = 2 # Gaussian-like smoothing (B=1, C=0).
    CATMULL_ROM = 3   # Sharp cubic interpolation. Good for upscaling.
    MITCHELL = 4      # Balanced sharpness/smoothness (B=1/3, C=1/3). Best general-purpose.
    POINT = 5         # Nearest-neighbor. No interpolation.


def is_block_compressed(fmt: BCFormat) -> bool:
    """Return True if the format uses block compression."""
    return fmt != BCFormat.A8R8G8B8


# DXGI_FORMAT values used in grcTexture
class DXGIFormat(IntEnum):
    BC1_UNORM = 71
    BC3_UNORM = 77
    BC4_UNORM = 80
    BC5_UNORM = 83
    BC7_UNORM = 98
    B8G8R8A8_UNORM = 87

BC_TO_DXGI = {
    BCFormat.BC1: DXGIFormat.BC1_UNORM,
    BCFormat.BC3: DXGIFormat.BC3_UNORM,
    BCFormat.BC4: DXGIFormat.BC4_UNORM,
    BCFormat.BC5: DXGIFormat.BC5_UNORM,
    BCFormat.BC7: DXGIFormat.BC7_UNORM,
    BCFormat.A8R8G8B8: DXGIFormat.B8G8R8A8_UNORM,
}

DXGI_TO_BC = {v: k for k, v in BC_TO_DXGI.items()}

# FourCC codes used in legacy DDS and YTD
FOURCC_DXT1 = 0x31545844
FOURCC_DXT5 = 0x35545844
FOURCC_ATI1 = 0x31495441
FOURCC_ATI2 = 0x32495441
FOURCC_BC7 = 0x20374342  # "BC7 "

BC_TO_FOURCC = {
    BCFormat.BC1: FOURCC_DXT1,
    BCFormat.BC3: FOURCC_DXT5,
    BCFormat.BC4: FOURCC_ATI1,
    BCFormat.BC5: FOURCC_ATI2,
}

FOURCC_TO_BC = {v: k for k, v in BC_TO_FOURCC.items()}

# DX9 format codes — used in compiled YTD resources (m_Format field).
# For BC formats these are FourCC values; for uncompressed, D3DFMT enum values.
D3DFMT_A8R8G8B8 = 21

BC_TO_DX9 = {
    BCFormat.BC1: FOURCC_DXT1,
    BCFormat.BC3: FOURCC_DXT5,
    BCFormat.BC4: FOURCC_ATI1,
    BCFormat.BC5: FOURCC_ATI2,
    BCFormat.BC7: FOURCC_BC7,
    BCFormat.A8R8G8B8: D3DFMT_A8R8G8B8,
}

DX9_TO_BC = {v: k for k, v in BC_TO_DX9.items()}


def block_byte_size(fmt: BCFormat) -> int:
    """Compressed block size in bytes (per 4x4 pixel block)."""
    return 8 if fmt in (BCFormat.BC1, BCFormat.BC4) else 16


def mip_data_size(width: int, height: int, fmt: BCFormat) -> int:
    """Data size for a single mip level."""
    if fmt == BCFormat.A8R8G8B8:
        return width * height * 4
    bw = max(1, (width + 3) // 4)
    bh = max(1, (height + 3) // 4)
    return bw * bh * block_byte_size(fmt)


def total_mip_data_size(width: int, height: int, fmt: BCFormat, levels: int) -> int:
    """Total data size across all mip levels."""
    total = 0
    w, h = width, height
    for _ in range(levels):
        total += mip_data_size(w, h, fmt)
        w = max(1, w // 2)
        h = max(1, h // 2)
    return total


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


# RSC8 texture format codes (DXGI-like byte values, used in RDR2 YTD)
class Rsc8TextureFormat(IntEnum):
    BC1_UNORM = 0x47
    BC1_UNORM_SRGB = 0x48
    BC3_UNORM = 0x4D
    BC3_UNORM_SRGB = 0x4E
    BC4_UNORM = 0x50
    BC5_UNORM = 0x53
    BC7_UNORM = 0x62
    BC7_UNORM_SRGB = 0x63
    B8G8R8A8_UNORM = 0x57
    B8G8R8A8_UNORM_SRGB = 0x5B

BC_TO_RSC8: dict[BCFormat, int] = {
    BCFormat.BC1: Rsc8TextureFormat.BC1_UNORM,
    BCFormat.BC3: Rsc8TextureFormat.BC3_UNORM,
    BCFormat.BC4: Rsc8TextureFormat.BC4_UNORM,
    BCFormat.BC5: Rsc8TextureFormat.BC5_UNORM,
    BCFormat.BC7: Rsc8TextureFormat.BC7_UNORM,
    BCFormat.A8R8G8B8: Rsc8TextureFormat.B8G8R8A8_UNORM,
}

RSC8_TO_BC: dict[int, BCFormat] = {v: k for k, v in BC_TO_RSC8.items()}

# SRGB variants map to the same BCFormat (same block encoding, different color space)
RSC8_TO_BC[Rsc8TextureFormat.BC1_UNORM_SRGB] = BCFormat.BC1
RSC8_TO_BC[Rsc8TextureFormat.BC3_UNORM_SRGB] = BCFormat.BC3
RSC8_TO_BC[Rsc8TextureFormat.BC7_UNORM_SRGB] = BCFormat.BC7
RSC8_TO_BC[Rsc8TextureFormat.B8G8R8A8_UNORM_SRGB] = BCFormat.A8R8G8B8


# RSC5 texture format codes (GTA IV WTD — FourCC / D3DFMT uint32 values)
class Rsc5TextureFormat(IntEnum):
    DXT1 = 0x31545844
    DXT3 = 0x33545844
    DXT5 = 0x35545844
    A8R8G8B8 = 21
    L8 = 50

BC_TO_RSC5: dict[BCFormat, int] = {
    BCFormat.BC1: Rsc5TextureFormat.DXT1,
    BCFormat.BC3: Rsc5TextureFormat.DXT5,
    BCFormat.A8R8G8B8: Rsc5TextureFormat.A8R8G8B8,
}

RSC5_TO_BC: dict[int, BCFormat] = {
    Rsc5TextureFormat.DXT1: BCFormat.BC1,
    Rsc5TextureFormat.DXT5: BCFormat.BC3,
    Rsc5TextureFormat.A8R8G8B8: BCFormat.A8R8G8B8,
}

# Formats NOT supported by GTA IV: BC4, BC5, BC7
_GTA4_UNSUPPORTED = frozenset({BCFormat.BC4, BCFormat.BC5, BCFormat.BC7})


def row_pitch(width: int, fmt: BCFormat) -> int:
    """Bytes per row (of blocks for BC, of pixels for uncompressed)."""
    if fmt == BCFormat.A8R8G8B8:
        return width * 4
    bw = max(1, (width + 3) // 4)
    return bw * block_byte_size(fmt)
