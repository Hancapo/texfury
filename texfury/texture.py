"""Texture class — the core unit of texfury."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from texfury import _native as native
from texfury.formats import BCFormat, MipFilter, BC_TO_DXGI, BC_TO_FOURCC, is_block_compressed

if TYPE_CHECKING:
    pass

# Try importing Pillow (optional)
try:
    from PIL import Image as PILImage
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


class Texture:
    """A compressed DDS texture with optional mipmaps.

    Create via class methods:
        Texture.from_image("photo.png")
        Texture.from_dds("existing.dds")
        Texture.from_pil(pil_image)
    """

    __slots__ = ("_data", "_width", "_height", "_format", "_mip_count",
                 "_mip_offsets", "_mip_sizes", "_name")

    def __init__(self, data: bytes, width: int, height: int,
                 fmt: BCFormat, mip_count: int,
                 mip_offsets: list[int], mip_sizes: list[int],
                 name: str = ""):
        self._data = data
        self._width = width
        self._height = height
        self._format = fmt
        self._mip_count = mip_count
        self._mip_offsets = mip_offsets
        self._mip_sizes = mip_sizes
        self._name = name

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def data(self) -> bytes:
        return self._data

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def format(self) -> BCFormat:
        return self._format

    @property
    def mip_count(self) -> int:
        return self._mip_count

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    # ── Factory methods ───────────────────────────────────────────────────

    @classmethod
    def from_image(cls, source: str | Path, *,
                   format: BCFormat = BCFormat.BC7,
                   quality: float = 0.7,
                   generate_mipmaps: bool = True,
                   min_mip_size: int = 4,
                   resize_to_pot: bool = True,
                   mip_filter: MipFilter = MipFilter.MITCHELL,
                   name: str = "") -> Texture:
        """Load an image file and compress it.

        Parameters
        ----------
        source : path
            Image file (PNG, JPG, TGA, BMP, PSD, WebP, etc.)
        format : BCFormat
            Target compression format.
        quality : float
            Compression quality 0.0 (fastest) to 1.0 (best).
        generate_mipmaps : bool
            Generate mipmap chain.
        min_mip_size : int
            Minimum dimension for smallest mip level.
        resize_to_pot : bool
            Resize to nearest power-of-two if needed.
        mip_filter : MipFilter
            Downsampling filter for mipmap generation and POT resize.
        name : str
            Texture name (defaults to filename stem).
        """
        path = Path(source)
        if not name:
            name = path.stem.lower()

        # Try native loader first (stb_image: PNG, JPG, TGA, BMP, PSD, WebP, etc.)
        # If it fails, fall back to Pillow for formats stb doesn't support (TIFF, etc.)
        try:
            img = native.load_image(str(path.resolve()))
        except OSError:
            if not _HAS_PIL:
                raise
            return cls.from_pil(PILImage.open(path), format=format,
                                quality=quality,
                                generate_mipmaps=generate_mipmaps,
                                min_mip_size=min_mip_size,
                                resize_to_pot=resize_to_pot,
                                mip_filter=mip_filter,
                                name=name)

        try:
            return cls._compress_image(img, format=format, quality=quality,
                                        generate_mipmaps=generate_mipmaps,
                                        min_mip_size=min_mip_size,
                                        resize_to_pot=resize_to_pot,
                                        mip_filter=mip_filter,
                                        name=name)
        finally:
            native.free_image(img)

    @classmethod
    def from_bytes(cls, data: bytes, *,
                   format: BCFormat = BCFormat.BC7,
                   quality: float = 0.7,
                   generate_mipmaps: bool = True,
                   min_mip_size: int = 4,
                   resize_to_pot: bool = True,
                   mip_filter: MipFilter = MipFilter.MITCHELL,
                   name: str = "") -> Texture:
        """Load an image from in-memory bytes and compress it.

        Accepts the raw file bytes of any image format supported by
        ``from_image`` (PNG, JPG, TGA, BMP, PSD, WebP, etc.).  If the
        native decoder (stb_image) cannot handle the data, Pillow is
        used as a fallback.

        Parameters
        ----------
        data : bytes
            Raw image file bytes (e.g. the contents of a PNG file).
        format : BCFormat
            Target compression format.
        quality : float
            Compression quality 0.0 (fastest) to 1.0 (best).
        generate_mipmaps : bool
            Generate mipmap chain.
        min_mip_size : int
            Minimum dimension for smallest mip level.
        resize_to_pot : bool
            Resize to nearest power-of-two if needed.
        mip_filter : MipFilter
            Downsampling filter for mipmap generation and POT resize.
        name : str
            Texture name.
        """
        # Try native decoder first (stb_image)
        try:
            img = native.load_image_memory(data)
        except OSError:
            if not _HAS_PIL:
                raise
            import io
            return cls.from_pil(PILImage.open(io.BytesIO(data)),
                                format=format, quality=quality,
                                generate_mipmaps=generate_mipmaps,
                                min_mip_size=min_mip_size,
                                resize_to_pot=resize_to_pot,
                                mip_filter=mip_filter,
                                name=name)

        try:
            return cls._compress_image(img, format=format, quality=quality,
                                        generate_mipmaps=generate_mipmaps,
                                        min_mip_size=min_mip_size,
                                        resize_to_pot=resize_to_pot,
                                        mip_filter=mip_filter,
                                        name=name)
        finally:
            native.free_image(img)

    @classmethod
    def from_pil(cls, image, *,
                 format: BCFormat = BCFormat.BC7,
                 quality: float = 0.7,
                 generate_mipmaps: bool = True,
                 min_mip_size: int = 4,
                 resize_to_pot: bool = True,
                 mip_filter: MipFilter = MipFilter.MITCHELL,
                 name: str = "") -> Texture:
        """Create a Texture from a PIL/Pillow Image object.

        Requires Pillow to be installed.
        """
        if not _HAS_PIL:
            raise ImportError("Pillow is required for from_pil(). "
                              "Install it with: pip install Pillow")

        rgba = image.convert("RGBA")
        raw = rgba.tobytes()
        img = native.create_image(rgba.width, rgba.height, raw)
        try:
            return cls._compress_image(img, format=format, quality=quality,
                                        generate_mipmaps=generate_mipmaps,
                                        min_mip_size=min_mip_size,
                                        resize_to_pot=resize_to_pot,
                                        mip_filter=mip_filter,
                                        name=name)
        finally:
            native.free_image(img)

    @classmethod
    def from_dds(cls, source: str | Path, *, name: str = "") -> Texture:
        """Load an existing DDS file."""
        path = Path(source)
        if not name:
            name = path.stem.lower()

        c = native.load_dds(str(path.resolve()))
        try:
            return cls._from_compressed_handle(c, name)
        finally:
            native.free_compressed(c)

    @staticmethod
    def inspect_dds(source: str | Path) -> dict:
        """Read DDS metadata without loading pixel data.

        Returns dict with keys: width, height, format, format_name, mip_count, data_size.
        """
        path = Path(source)
        c = native.load_dds(str(path.resolve()))
        try:
            fmt = BCFormat(native.compressed_format(c))
            return {
                "name": path.stem.lower(),
                "width": native.compressed_width(c),
                "height": native.compressed_height(c),
                "format": fmt,
                "format_name": fmt.name,
                "mip_count": native.compressed_mip_count(c),
                "data_size": native.compressed_size(c),
            }
        finally:
            native.free_compressed(c)

    @classmethod
    def from_raw(cls, data: bytes, width: int, height: int,
                 fmt: BCFormat, mip_count: int,
                 mip_offsets: list[int], mip_sizes: list[int],
                 name: str = "") -> Texture:
        """Create from raw compressed pixel data (for internal use)."""
        return cls(data, width, height, fmt, mip_count,
                   mip_offsets, mip_sizes, name)

    # ── Output ────────────────────────────────────────────────────────────

    def save_dds(self, path: str | Path) -> None:
        """Write this texture as a DDS file."""
        Path(path).write_bytes(self.to_dds_bytes())

    def to_dds_bytes(self) -> bytes:
        """Return complete DDS file as bytes."""
        return _build_dds_bytes(self._width, self._height, self._format,
                                self._mip_count, self._mip_sizes, self._data)

    def to_rgba(self, mip: int = 0) -> tuple[bytes, int, int]:
        """Decompress to raw RGBA pixels.

        Returns (rgba_bytes, width, height) for the given mip level.
        """
        c = self._to_compressed_handle()
        try:
            return native.decompress(c, mip)
        finally:
            native.free_compressed(c)

    def to_pil(self, mip: int = 0):
        """Decompress to a Pillow Image. Requires Pillow.

        Returns a PIL.Image.Image in RGBA mode.
        """
        if not _HAS_PIL:
            raise ImportError("Pillow is required for to_pil(). "
                              "Install it with: pip install Pillow")
        rgba, w, h = self.to_rgba(mip)
        return PILImage.frombytes("RGBA", (w, h), rgba)

    def quality_metrics(self, original_rgba: bytes) -> dict:
        """Compare this texture against original RGBA pixels.

        Parameters
        ----------
        original_rgba : bytes
            Original uncompressed RGBA pixel data (same dimensions as mip 0).

        Returns
        -------
        dict with keys: psnr_rgb, psnr_rgba, ssim
        """
        decompressed, w, h = self.to_rgba(0)
        return {
            "psnr_rgb": native.psnr(original_rgba, decompressed, w, h, 3),
            "psnr_rgba": native.psnr(original_rgba, decompressed, w, h, 4),
            "ssim": native.ssim(original_rgba, decompressed, w, h),
        }

    def validate(self) -> list[str]:
        """Check texture for common issues.

        Returns a list of warning strings. Empty list means everything is OK.
        """
        warnings = []
        w, h = self._width, self._height

        if w <= 0 or h <= 0:
            warnings.append(f"Invalid dimensions: {w}x{h}")

        if w & (w - 1) != 0 or h & (h - 1) != 0:
            warnings.append(f"Non-power-of-two dimensions: {w}x{h}")

        if is_block_compressed(self._format):
            if w < 4 or h < 4:
                warnings.append(
                    f"Dimensions {w}x{h} below minimum 4x4 for "
                    f"{self._format.name}")

        if self._mip_count < 1:
            warnings.append("No mip levels")

        from texfury.formats import total_mip_data_size
        expected = total_mip_data_size(w, h, self._format, self._mip_count)
        actual = len(self._data)
        if actual != expected:
            warnings.append(
                f"Data size mismatch: expected {expected} bytes, "
                f"got {actual} bytes")

        if w > 16384 or h > 16384:
            warnings.append(f"Dimensions {w}x{h} exceed 16384 max")

        if not self._name:
            warnings.append("Texture has no name")

        return warnings

    # ── Internal ──────────────────────────────────────────────────────────

    def _to_compressed_handle(self):
        """Build a native TfCompressed handle from this texture's data."""
        import ctypes
        # We need to pass the data to the native layer. Create a TfCompressed
        # by saving to DDS and loading back (roundtrip via memory).
        dds = self.to_dds_bytes()
        # Write to temp file and load
        import tempfile, os
        fd, tmp = tempfile.mkstemp(suffix=".dds")
        try:
            os.write(fd, dds)
            os.close(fd)
            return native.load_dds(tmp)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    @classmethod
    def _compress_image(cls, img, *, format: BCFormat, quality: float,
                        generate_mipmaps: bool, min_mip_size: int,
                        resize_to_pot: bool, mip_filter: MipFilter,
                        name: str) -> Texture:
        work_img = img
        resized = None

        if resize_to_pot and not native.is_power_of_two(
                native.image_width(img), native.image_height(img)):
            resized = native.resize_to_pot(img, int(mip_filter))
            work_img = resized

        try:
            c = native.compress(work_img, int(format), generate_mipmaps,
                                min_mip_size, quality, int(mip_filter))
            try:
                return cls._from_compressed_handle(c, name)
            finally:
                native.free_compressed(c)
        finally:
            if resized is not None:
                native.free_image(resized)

    @classmethod
    def _from_compressed_handle(cls, c, name: str) -> Texture:
        data = native.compressed_data(c)
        width = native.compressed_width(c)
        height = native.compressed_height(c)
        fmt = BCFormat(native.compressed_format(c))
        mip_count = native.compressed_mip_count(c)
        offsets = [native.compressed_mip_offset(c, i) for i in range(mip_count)]
        sizes = [native.compressed_mip_size(c, i) for i in range(mip_count)]
        return cls(data, width, height, fmt, mip_count, offsets, sizes, name)

    def __repr__(self) -> str:
        return (f"Texture(name={self._name!r}, {self._width}x{self._height}, "
                f"format={self._format.name}, mips={self._mip_count})")


# ── DDS file builder ─────────────────────────────────────────────────────────

_DDS_MAGIC = 0x20534444
_DDSD_CAPS = 0x1
_DDSD_HEIGHT = 0x2
_DDSD_WIDTH = 0x4
_DDSD_PITCH = 0x8
_DDSD_PIXELFORMAT = 0x1000
_DDSD_MIPMAPCOUNT = 0x20000
_DDSD_LINEARSIZE = 0x80000
_DDPF_ALPHAPIXELS = 0x1
_DDPF_FOURCC = 0x4
_DDPF_RGB = 0x40
_DDSCAPS_TEXTURE = 0x1000
_DDSCAPS_COMPLEX = 0x8
_DDSCAPS_MIPMAP = 0x400000


def _build_dds_bytes(width: int, height: int, fmt: BCFormat,
                     mip_count: int, mip_sizes: list[int],
                     pixel_data: bytes) -> bytes:
    """Build a complete DDS file from pixel data."""
    uncompressed = not is_block_compressed(fmt)
    use_dx10 = (not uncompressed) and fmt in (BCFormat.BC4, BCFormat.BC5, BCFormat.BC7)

    hdr = bytearray(124)
    struct.pack_into("<I", hdr, 0, 124)  # size

    if uncompressed:
        flags = _DDSD_CAPS | _DDSD_HEIGHT | _DDSD_WIDTH | _DDSD_PIXELFORMAT | _DDSD_PITCH
    else:
        flags = _DDSD_CAPS | _DDSD_HEIGHT | _DDSD_WIDTH | _DDSD_PIXELFORMAT | _DDSD_LINEARSIZE
    if mip_count > 1:
        flags |= _DDSD_MIPMAPCOUNT
    struct.pack_into("<I", hdr, 4, flags)
    struct.pack_into("<I", hdr, 8, height)
    struct.pack_into("<I", hdr, 12, width)

    if uncompressed:
        struct.pack_into("<I", hdr, 16, width * 4)  # row pitch
    else:
        struct.pack_into("<I", hdr, 16, mip_sizes[0] if mip_sizes else 0)

    struct.pack_into("<I", hdr, 20, 1)  # depth
    struct.pack_into("<I", hdr, 24, mip_count)
    # reserved1[11] stays zero

    # Pixel format at header offset 72
    struct.pack_into("<I", hdr, 72, 32)   # pf.size

    if uncompressed:
        struct.pack_into("<I", hdr, 76, _DDPF_RGB | _DDPF_ALPHAPIXELS)
        struct.pack_into("<I", hdr, 84, 32)          # rgbBitCount
        struct.pack_into("<I", hdr, 88, 0x00FF0000)  # rBitMask
        struct.pack_into("<I", hdr, 92, 0x0000FF00)  # gBitMask
        struct.pack_into("<I", hdr, 96, 0x000000FF)  # bBitMask
        struct.pack_into("<I", hdr, 100, 0xFF000000)  # aBitMask
    else:
        struct.pack_into("<I", hdr, 76, _DDPF_FOURCC)
        if use_dx10:
            struct.pack_into("<I", hdr, 80, 0x30315844)  # "DX10"
        elif fmt == BCFormat.BC1:
            struct.pack_into("<I", hdr, 80, 0x31545844)  # "DXT1"
        else:
            struct.pack_into("<I", hdr, 80, 0x35545844)  # "DXT5"

    caps = _DDSCAPS_TEXTURE
    if mip_count > 1:
        caps |= _DDSCAPS_COMPLEX | _DDSCAPS_MIPMAP
    struct.pack_into("<I", hdr, 104, caps)

    parts = [struct.pack("<I", _DDS_MAGIC), bytes(hdr)]

    if use_dx10:
        dx10 = bytearray(20)
        struct.pack_into("<I", dx10, 0, int(BC_TO_DXGI[fmt]))
        struct.pack_into("<I", dx10, 4, 3)  # D3D10_RESOURCE_DIMENSION_TEXTURE2D
        struct.pack_into("<I", dx10, 12, 1)  # arraySize
        parts.append(bytes(dx10))

    parts.append(pixel_data)
    return b"".join(parts)
