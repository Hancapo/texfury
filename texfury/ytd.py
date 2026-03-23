"""YTD (Texture Dictionary) file creation and extraction for GTA V."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Callable

from texfury.formats import (
    BCFormat, BC_TO_DXGI, BC_TO_FOURCC, FOURCC_TO_BC, DXGI_TO_BC,
    BC_TO_DX9, DX9_TO_BC,
    row_pitch, total_mip_data_size, mip_data_size, is_block_compressed,
)
from texfury.resource import (
    DAT_VIRTUAL_BASE, DAT_PHYSICAL_BASE,
    build_rsc7, decompress_rsc7,
)
from texfury.texture import Texture

# ── JOAAT hash ────────────────────────────────────────────────────────────────

def _joaat(text: str) -> int:
    h = 0
    for c in text.lower():
        h = (h + ord(c)) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= (h >> 6)
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= (h >> 11)
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


def _align(offset: int, alignment: int) -> int:
    return (offset + alignment - 1) & ~(alignment - 1)


GRC_TEXTURE_SIZE = 0x90
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tiff",
                    ".tif", ".webp", ".psd", ".gif", ".hdr"}


# ── YTDFile ───────────────────────────────────────────────────────────────────

class YTDFile:
    """GTA V texture dictionary (.ytd) file.

    Usage:
        ytd = YTDFile()
        ytd.add(Texture.from_image("logo.png"))
        ytd.save("output.ytd")

        ytd = YTDFile.load("existing.ytd")
        for tex in ytd.textures:
            tex.save_dds(f"{tex.name}.dds")
    """

    __slots__ = ("_textures",)

    def __init__(self) -> None:
        self._textures: list[Texture] = []

    @property
    def textures(self) -> list[Texture]:
        return list(self._textures)

    def add(self, texture: Texture) -> None:
        """Add a texture to the dictionary."""
        if not texture.name:
            raise ValueError("Texture must have a name before adding to YTD")
        self._textures.append(texture)

    def save(self, path: str | Path) -> None:
        """Build and write the YTD to a file."""
        data = _build_ytd(self._textures)
        Path(path).write_bytes(data)

    @staticmethod
    def load(path: str | Path) -> YTDFile:
        """Read a YTD file and extract its textures."""
        return _parse_ytd(Path(path).read_bytes())

    def __len__(self) -> int:
        return len(self._textures)

    def __repr__(self) -> str:
        names = [t.name for t in self._textures]
        return f"YTDFile(textures={names})"


# ── High-level convenience functions ──────────────────────────────────────────

def create_ytd_from_folder(
    folder: str | Path,
    output: str | Path | None = None,
    *,
    format: BCFormat = BCFormat.BC7,
    quality: float = 0.7,
    generate_mipmaps: bool = True,
    min_mip_size: int = 4,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Create a YTD from all images in a folder.

    Parameters
    ----------
    folder : path
        Directory containing image files.
    output : path, optional
        Output .ytd path. Defaults to <folder_name>.ytd next to the folder.
    format : BCFormat
        Compression format for all textures.
    quality : float
        Compression quality (0.0–1.0).
    generate_mipmaps : bool
        Generate mipmap chains.
    min_mip_size : int
        Minimum dimension for smallest mip.
    on_progress : callable, optional
        Progress callback: (current_index, total_count, texture_name).

    Returns
    -------
    Path to the created YTD file.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Not a directory: {folder}")

    if output is None:
        output = folder.parent / f"{folder.name}.ytd"
    output = Path(output)

    files = sorted(
        f for f in folder.iterdir()
        if f.suffix.lower() in IMAGE_EXTENSIONS or f.suffix.lower() == ".dds"
    )
    if not files:
        raise FileNotFoundError(f"No image files found in {folder}")

    ytd = YTDFile()
    total = len(files)
    for i, f in enumerate(files):
        name = f.stem.lower()
        if on_progress:
            on_progress(i + 1, total, name)

        if f.suffix.lower() == ".dds":
            tex = Texture.from_dds(f, name=name)
        else:
            tex = Texture.from_image(f, format=format, quality=quality,
                                     generate_mipmaps=generate_mipmaps,
                                     min_mip_size=min_mip_size, name=name)
        ytd.add(tex)

    ytd.save(output)
    return output


def batch_convert(
    folder: str | Path,
    output_dir: str | Path | None = None,
    *,
    format: BCFormat = BCFormat.BC7,
    quality: float = 0.7,
    generate_mipmaps: bool = True,
    min_mip_size: int = 4,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Convert all images in a folder to DDS files.

    Parameters
    ----------
    folder : path
        Directory containing image files.
    output_dir : path, optional
        Output directory. Defaults to <folder>/dds_out.
    format : BCFormat
        Compression format.
    quality : float
        Compression quality (0.0–1.0).
    generate_mipmaps : bool
        Generate mipmap chains.
    min_mip_size : int
        Minimum dimension for smallest mip.
    on_progress : callable, optional
        Progress callback: (current_index, total_count, texture_name).

    Returns
    -------
    Path to the output directory.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Not a directory: {folder}")

    if output_dir is None:
        output_dir = folder / "dds_out"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        f for f in folder.iterdir()
        if f.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not files:
        raise FileNotFoundError(f"No image files found in {folder}")

    total = len(files)
    for i, f in enumerate(files):
        name = f.stem.lower()
        if on_progress:
            on_progress(i + 1, total, name)

        tex = Texture.from_image(f, format=format, quality=quality,
                                 generate_mipmaps=generate_mipmaps,
                                 min_mip_size=min_mip_size, name=name)
        tex.save_dds(output_dir / f"{name}.dds")

    return output_dir


def extract_ytd(
    ytd_path: str | Path,
    output_dir: str | Path | None = None,
) -> Path:
    """Extract all textures from a YTD as DDS files.

    Returns the output directory path.
    """
    ytd_path = Path(ytd_path)
    if output_dir is None:
        output_dir = ytd_path.parent / ytd_path.stem
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ytd = YTDFile.load(ytd_path)
    for tex in ytd.textures:
        tex.save_dds(output_dir / f"{tex.name}.dds")
    return output_dir


# ── YTD binary builder ────────────────────────────────────────────────────────

def _large_mip_data_size(w: int, h: int, fmt: BCFormat, levels: int) -> int:
    total = 0
    for lvl in range(levels):
        mw = max(1, w >> lvl)
        mh = max(1, h >> lvl)
        if mw >= 16 and mh >= 16:
            total += mip_data_size(mw, mh, fmt)
    return total


def _build_ytd(textures: list[Texture]) -> bytes:
    entries = sorted(textures, key=lambda t: _joaat(t.name))
    n = len(entries)
    if n == 0:
        raise ValueError("Cannot create YTD with zero textures")

    # Phase 1: virtual data layout
    dict_size = 0x40
    keys_offset = dict_size
    keys_size = 4 * n

    ptrs_offset = _align(keys_offset + keys_size, 16)
    ptrs_size = 8 * n

    textures_offset = _align(ptrs_offset + ptrs_size, 16)
    textures_size = GRC_TEXTURE_SIZE * n

    names_offset = textures_offset + textures_size
    name_bytes_list: list[bytes] = []
    name_offsets: list[int] = []
    cur = names_offset
    for e in entries:
        encoded = e.name.encode("utf-8") + b"\x00"
        name_offsets.append(cur)
        name_bytes_list.append(encoded)
        cur += len(encoded)

    pagemap_offset = _align(cur, 16)
    virtual_size = pagemap_offset + 0x10

    # Phase 2: physical data layout
    phys_offsets: list[int] = []
    phys_cur = 0
    for e in entries:
        phys_offsets.append(phys_cur)
        phys_cur += len(e.data)
    physical_size = phys_cur

    # Phase 3: build virtual buffer
    vbuf = bytearray(virtual_size)

    keys_vaddr = DAT_VIRTUAL_BASE + keys_offset
    ptrs_vaddr = DAT_VIRTUAL_BASE + ptrs_offset
    pagemap_vaddr = DAT_VIRTUAL_BASE + pagemap_offset

    struct.pack_into("<Q", vbuf, 0x00, 0)
    struct.pack_into("<Q", vbuf, 0x08, pagemap_vaddr)
    struct.pack_into("<Q", vbuf, 0x10, 0)
    struct.pack_into("<I", vbuf, 0x18, 1)
    struct.pack_into("<I", vbuf, 0x1C, 0)
    struct.pack_into("<Q", vbuf, 0x20, keys_vaddr)
    struct.pack_into("<HH", vbuf, 0x28, n, n)
    struct.pack_into("<I", vbuf, 0x2C, 0)
    struct.pack_into("<Q", vbuf, 0x30, ptrs_vaddr)
    struct.pack_into("<HH", vbuf, 0x38, n, n)
    struct.pack_into("<I", vbuf, 0x3C, 0)

    for i, e in enumerate(entries):
        struct.pack_into("<I", vbuf, keys_offset + 4 * i, _joaat(e.name))

    for i in range(n):
        tex_vaddr = DAT_VIRTUAL_BASE + textures_offset + GRC_TEXTURE_SIZE * i
        struct.pack_into("<Q", vbuf, ptrs_offset + 8 * i, tex_vaddr)

    for i, e in enumerate(entries):
        off = textures_offset + GRC_TEXTURE_SIZE * i
        fmt = e.format

        # YTD stores DX9 format codes (FourCC for BC, D3DFMT for uncompressed)
        format_val = BC_TO_DX9[fmt]

        stride = row_pitch(e.width, fmt)
        name_vaddr = DAT_VIRTUAL_BASE + name_offsets[i]
        data_paddr = DAT_PHYSICAL_BASE + phys_offsets[i]
        data_size_large = _large_mip_data_size(e.width, e.height, fmt, e.mip_count)

        struct.pack_into("<Q", vbuf, off + 0x00, 0)
        struct.pack_into("<q", vbuf, off + 0x08, 0)
        struct.pack_into("<q", vbuf, off + 0x10, 0)
        struct.pack_into("<Q", vbuf, off + 0x18, 0)
        struct.pack_into("<Q", vbuf, off + 0x20, 0)
        struct.pack_into("<Q", vbuf, off + 0x28, name_vaddr)
        struct.pack_into("<h", vbuf, off + 0x30, 1)
        struct.pack_into("<b", vbuf, off + 0x32, 0)
        struct.pack_into("<b", vbuf, off + 0x33, 0)
        struct.pack_into("<i", vbuf, off + 0x34, 0)
        struct.pack_into("<Q", vbuf, off + 0x38, 0)
        struct.pack_into("<I", vbuf, off + 0x40, data_size_large)
        struct.pack_into("<i", vbuf, off + 0x44, 0)
        struct.pack_into("<i", vbuf, off + 0x48, 0)
        struct.pack_into("<h", vbuf, off + 0x4C, 0)
        struct.pack_into("<h", vbuf, off + 0x4E, 0)
        struct.pack_into("<h", vbuf, off + 0x50, e.width)
        struct.pack_into("<h", vbuf, off + 0x52, e.height)
        struct.pack_into("<h", vbuf, off + 0x54, 1)
        struct.pack_into("<h", vbuf, off + 0x56, stride)
        struct.pack_into("<I", vbuf, off + 0x58, format_val)
        struct.pack_into("<B", vbuf, off + 0x5C, 0)
        struct.pack_into("<B", vbuf, off + 0x5D, e.mip_count)
        struct.pack_into("<B", vbuf, off + 0x5E, 0)
        struct.pack_into("<B", vbuf, off + 0x5F, 0)
        struct.pack_into("<Q", vbuf, off + 0x60, 0)
        struct.pack_into("<Q", vbuf, off + 0x68, 0)
        struct.pack_into("<Q", vbuf, off + 0x70, data_paddr)
        struct.pack_into("<Q", vbuf, off + 0x78, 0)
        struct.pack_into("<q", vbuf, off + 0x80, 0)
        struct.pack_into("<q", vbuf, off + 0x88, 0)

    for i, name_data in enumerate(name_bytes_list):
        start = name_offsets[i]
        vbuf[start:start + len(name_data)] = name_data

    struct.pack_into("<B", vbuf, pagemap_offset, 1)
    struct.pack_into("<B", vbuf, pagemap_offset + 1, 1)

    # Phase 4: physical data
    pbuf = bytearray()
    for e in entries:
        pbuf.extend(e.data)

    return build_rsc7(bytes(vbuf), bytes(pbuf))


# ── YTD parser ────────────────────────────────────────────────────────────────

def _r_u8(d: bytes, o: int) -> int: return d[o]
def _r_u16(d: bytes, o: int) -> int: return struct.unpack_from("<H", d, o)[0]
def _r_i16(d: bytes, o: int) -> int: return struct.unpack_from("<h", d, o)[0]
def _r_u32(d: bytes, o: int) -> int: return struct.unpack_from("<I", d, o)[0]
def _r_u64(d: bytes, o: int) -> int: return struct.unpack_from("<Q", d, o)[0]
def _v2o(addr: int) -> int: return addr - DAT_VIRTUAL_BASE
def _p2o(addr: int) -> int: return addr - DAT_PHYSICAL_BASE


def _parse_ytd(file_data: bytes) -> YTDFile:
    virtual_data, physical_data = decompress_rsc7(file_data)

    count = _r_u16(virtual_data, 0x28)
    keys_ptr = _r_u64(virtual_data, 0x20)
    items_ptr = _r_u64(virtual_data, 0x30)
    keys_off = _v2o(keys_ptr)
    items_off = _v2o(items_ptr)

    ytd = YTDFile()

    for i in range(count):
        tex_ptr = _r_u64(virtual_data, items_off + 8 * i)
        tex_off = _v2o(tex_ptr)

        name_ptr = _r_u64(virtual_data, tex_off + 0x28)
        width = _r_i16(virtual_data, tex_off + 0x50)
        height = _r_i16(virtual_data, tex_off + 0x52)
        format_val = _r_u32(virtual_data, tex_off + 0x58)
        mip_levels = _r_u8(virtual_data, tex_off + 0x5D)
        data_ptr = _r_u64(virtual_data, tex_off + 0x70)

        name_off = _v2o(name_ptr)
        name_end = virtual_data.index(b"\x00", name_off)
        name = virtual_data[name_off:name_end].decode("utf-8", errors="replace")

        # Determine format from DX9 code (FourCC for BC, D3DFMT for uncompressed)
        if format_val in DX9_TO_BC:
            fmt = DX9_TO_BC[format_val]
        elif format_val in FOURCC_TO_BC:
            fmt = FOURCC_TO_BC[format_val]
        elif format_val in DXGI_TO_BC:
            fmt = DXGI_TO_BC[format_val]
        else:
            raise ValueError(f"Unsupported texture format in YTD: 0x{format_val:08X}")

        phys_off = _p2o(data_ptr)
        data_size = total_mip_data_size(width, height, fmt, mip_levels)
        pixel_data = physical_data[phys_off:phys_off + data_size]

        # Build mip offsets/sizes
        offsets, sizes = [], []
        w, h, off = width, height, 0
        for _ in range(mip_levels):
            ms = mip_data_size(w, h, fmt)
            offsets.append(off)
            sizes.append(ms)
            off += ms
            w = max(1, w // 2)
            h = max(1, h // 2)

        tex = Texture.from_raw(pixel_data, width, height, fmt,
                               mip_levels, offsets, sizes, name)
        ytd.add(tex)

    return ytd
