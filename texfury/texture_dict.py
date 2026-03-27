"""Internal Texture Dictionary (ITD) — unified texture dictionary handling for RAGE games."""

from __future__ import annotations

import struct
from enum import Enum
from pathlib import Path
from typing import Callable

from texfury.formats import (
    BCFormat, MipFilter,
    BC_TO_DX9, DX9_TO_BC, FOURCC_TO_BC, DXGI_TO_BC,
    BC_TO_RSC8, RSC8_TO_BC,
    BC_TO_RSC5, RSC5_TO_BC, _GTA4_UNSUPPORTED,
    row_pitch, total_mip_data_size, mip_data_size, is_block_compressed,
)
from texfury.rsc import (
    DAT_VIRTUAL_BASE, DAT_PHYSICAL_BASE,
    RSC5_MAGIC, build_rsc5, decompress_rsc5,
    RSC7_MAGIC, build_rsc7, decompress_rsc7, parse_rsc7_header,
    RSC8_MAGIC, build_rsc8, decompress_rsc8,
)
from texfury.texture import Texture


# ── Game enum ────────────────────────────────────────────────────────────────

class Game(str, Enum):
    """Target game / edition for texture dictionaries."""
    GTA4 = "gta4"
    GTA5 = "gta5"
    GTA5_GEN9 = "gta5_enhanced"
    RDR2 = "rdr2"


# ── Shared helpers ───────────────────────────────────────────────────────────

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


def _r_u8(d: bytes, o: int) -> int: return d[o]
def _r_u16(d: bytes, o: int) -> int: return struct.unpack_from("<H", d, o)[0]
def _r_i16(d: bytes, o: int) -> int: return struct.unpack_from("<h", d, o)[0]
def _r_u32(d: bytes, o: int) -> int: return struct.unpack_from("<I", d, o)[0]
def _r_u64(d: bytes, o: int) -> int: return struct.unpack_from("<Q", d, o)[0]
def _v2o(addr: int) -> int: return addr - DAT_VIRTUAL_BASE
def _p2o(addr: int) -> int: return addr - DAT_PHYSICAL_BASE


def _detect_game(file_data: bytes) -> Game:
    """Detect game from the RSC magic bytes and version."""
    if len(file_data) < 12:
        raise ValueError("File too short to detect format")
    magic = struct.unpack_from("<I", file_data, 0)[0]
    if magic == RSC5_MAGIC:
        return Game.GTA4
    if magic == RSC7_MAGIC:
        version = struct.unpack_from("<I", file_data, 4)[0]
        if version == 5:
            return Game.GTA5_GEN9
        return Game.GTA5
    if magic == RSC8_MAGIC:
        return Game.RDR2
    raise ValueError(f"Unknown texture dictionary format — magic: 0x{magic:08X}")


def _build_mip_info(
    width: int, height: int, fmt: BCFormat, mip_count: int,
) -> tuple[list[int], list[int]]:
    """Build mip offset/size lists. Shared by both games."""
    offsets, sizes = [], []
    w, h, off = width, height, 0
    for _ in range(mip_count):
        ms = mip_data_size(w, h, fmt)
        offsets.append(off)
        sizes.append(ms)
        off += ms
        w = max(1, w // 2)
        h = max(1, h // 2)
    return offsets, sizes


def _read_name(virtual_data: bytes, name_ptr: int) -> str:
    name_off = _v2o(name_ptr)
    name_end = virtual_data.index(b"\x00", name_off)
    return virtual_data[name_off:name_end].decode("utf-8", errors="replace")


def _block_stride(fmt: BCFormat) -> int:
    """Block stride in bytes. Used by RDR2 and GTA V Enhanced."""
    if fmt in (BCFormat.BC1, BCFormat.BC4):
        return 8
    if fmt in (BCFormat.BC3, BCFormat.BC5, BCFormat.BC7):
        return 16
    return 4  # A8R8G8B8 / uncompressed


def _block_count(fmt: BCFormat, w: int, h: int, depth: int, mips: int,
                 *, align: int | None = None) -> int:
    """Total block count across all mip levels.

    Parameters
    ----------
    align : int or None
        Block alignment per axis.  ``None`` (default) uses RDR2-style
        alignment (16 for stride==1, else 8).  Pass ``1`` for GTA V
        Enhanced which has no alignment padding.
    """
    bs = _block_stride(fmt)
    bp = 4 if is_block_compressed(fmt) else 1

    bw, bh = w, h
    if mips > 1:
        bw = 1
        while bw < w:
            bw *= 2
        bh = 1
        while bh < h:
            bh *= 2

    if align is None:
        align = 16 if bs == 1 else 8
    bc = 0
    for _ in range(mips):
        bx = max(1, (bw + bp - 1) // bp)
        by = max(1, (bh + bp - 1) // bp)
        bx += (align - (bx % align)) % align
        by += (align - (by % align)) % align
        bc += bx * by * depth
        bw //= 2
        bh //= 2

    return bc


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tiff",
                    ".tif", ".webp", ".psd", ".gif", ".hdr"}


# ── ITD ──────────────────────────────────────────────────────────────────

class ITD:
    """Internal Texture Dictionary — generic abstraction over RAGE texture
    dictionary formats (.wtd for x32, .ytd for x64).

    Usage:
        td = ITD()                          # GTA V Legacy by default
        td = ITD(game=Game.GTA4)            # GTA IV (.wtd)
        td = ITD(game=Game.GTA5_GEN9)   # GTA V Enhanced
        td = ITD(game=Game.RDR2)            # RDR2

        td.add(Texture.from_image("logo.png"))
        td.save("output.ytd")

        td = ITD.load("existing.ytd")       # auto-detects game
    """

    __slots__ = ("_textures", "_game")

    def __init__(self, game: Game = Game.GTA5) -> None:
        self._textures: list[Texture] = []
        self._game: Game = game

    @property
    def game(self) -> Game:
        return self._game

    @property
    def textures(self) -> list[Texture]:
        return list(self._textures)

    def add(self, texture: Texture) -> None:
        """Add a texture to the dictionary."""
        if not texture.name:
            raise ValueError("Texture must have a name before adding to a dictionary")
        self._textures.append(texture)

    def replace(self, name: str, texture: Texture) -> None:
        """Replace a texture by name. Raises KeyError if not found."""
        lower = name.lower()
        for i, t in enumerate(self._textures):
            if t.name.lower() == lower:
                if texture.name != t.name:
                    texture.name = t.name
                self._textures[i] = texture
                return
        raise KeyError(f"Texture '{name}' not found in dictionary")

    def remove(self, name: str) -> None:
        """Remove a texture by name. Raises KeyError if not found."""
        lower = name.lower()
        for i, t in enumerate(self._textures):
            if t.name.lower() == lower:
                self._textures.pop(i)
                return
        raise KeyError(f"Texture '{name}' not found in dictionary")

    def get(self, name: str) -> Texture:
        """Get a texture by name. Raises KeyError if not found."""
        lower = name.lower()
        for t in self._textures:
            if t.name.lower() == lower:
                return t
        raise KeyError(f"Texture '{name}' not found in dictionary")

    def names(self) -> list[str]:
        """Return the names of all textures."""
        return [t.name for t in self._textures]

    def save(self, path: str | Path) -> None:
        """Build and write the texture dictionary to a file."""
        builders = {
            Game.GTA4: _build_gta4,
            Game.GTA5: _build_gtav,
            Game.GTA5_GEN9: _build_enhanced,
            Game.RDR2: _build_rdr2,
        }
        data = builders[self._game](self._textures)
        Path(path).write_bytes(data)

    @staticmethod
    def load(path: str | Path) -> ITD:
        """Read a texture dictionary — auto-detects game from header."""
        file_data = Path(path).read_bytes()
        game = _detect_game(file_data)
        parsers = {
            Game.GTA4: _parse_gta4,
            Game.GTA5: _parse_gtav,
            Game.GTA5_GEN9: _parse_enhanced,
            Game.RDR2: _parse_rdr2,
        }
        return parsers[game](file_data)

    @staticmethod
    def inspect(path: str | Path) -> list[dict]:
        """Read texture metadata without loading pixel data. Auto-detects game."""
        file_data = Path(path).read_bytes()
        game = _detect_game(file_data)
        inspectors = {
            Game.GTA4: _inspect_gta4,
            Game.GTA5: _inspect_gtav,
            Game.GTA5_GEN9: _inspect_enhanced,
            Game.RDR2: _inspect_rdr2,
        }
        return inspectors[game](file_data)

    def __len__(self) -> int:
        return len(self._textures)

    def __contains__(self, name: str) -> bool:
        lower = name.lower()
        return any(t.name.lower() == lower for t in self._textures)

    def __repr__(self) -> str:
        names = [t.name for t in self._textures]
        return f"ITD(game={self._game.value}, textures={names})"


# ── Convenience functions ────────────────────────────────────────────────────

def create_dict_from_folder(
    folder: str | Path,
    output: str | Path | None = None,
    *,
    game: Game = Game.GTA5,
    format: BCFormat = BCFormat.BC7,
    quality: float = 0.7,
    generate_mipmaps: bool = True,
    min_mip_size: int = 4,
    mip_filter: MipFilter = MipFilter.MITCHELL,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Create a texture dictionary from all images in a folder.

    Parameters
    ----------
    folder : path
        Directory containing image files.
    output : path, optional
        Output path. Defaults to <folder_name>.ytd next to the folder.
    game : Game
        Target game. Defaults to GTAV_LEGACY.
    format : BCFormat
        Compression format for all textures.
    quality : float
        Compression quality (0.0–1.0).
    generate_mipmaps : bool
        Generate mipmap chains.
    min_mip_size : int
        Minimum dimension for smallest mip.
    mip_filter : MipFilter
        Downsampling filter for mipmap generation.
    on_progress : callable, optional
        Progress callback: (current_index, total_count, texture_name).

    Returns
    -------
    Path to the created texture dictionary file.
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

    td = ITD(game=game)
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
                                     min_mip_size=min_mip_size,
                                     mip_filter=mip_filter, name=name)
        td.add(tex)

    td.save(output)
    return output


def batch_convert(
    folder: str | Path,
    output_dir: str | Path | None = None,
    *,
    format: BCFormat = BCFormat.BC7,
    quality: float = 0.7,
    generate_mipmaps: bool = True,
    min_mip_size: int = 4,
    mip_filter: MipFilter = MipFilter.MITCHELL,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Convert all images in a folder to DDS files."""
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
                                 min_mip_size=min_mip_size,
                                 mip_filter=mip_filter, name=name)
        tex.save_dds(output_dir / f"{name}.dds")

    return output_dir


def extract_dict(
    dict_path: str | Path,
    output_dir: str | Path | None = None,
) -> Path:
    """Extract all textures from a texture dictionary as DDS files. Auto-detects game."""
    dict_path = Path(dict_path)
    if output_dir is None:
        output_dir = dict_path.parent / dict_path.stem
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    td = ITD.load(dict_path)
    for tex in td.textures:
        tex.save_dds(output_dir / f"{tex.name}.dds")
    return output_dir


# ═════════════════════════════════════════════════════════════════════════════
# GTA V (RSC7) internals
# ═════════════════════════════════════════════════════════════════════════════

_GTAV_TEX_SIZE = 0x90  # 144 bytes


def _resolve_gtav_format(format_val: int) -> BCFormat | None:
    if format_val in DX9_TO_BC:
        return DX9_TO_BC[format_val]
    if format_val in FOURCC_TO_BC:
        return FOURCC_TO_BC[format_val]
    if format_val in DXGI_TO_BC:
        return DXGI_TO_BC[format_val]
    return None


def _large_mip_data_size(w: int, h: int, fmt: BCFormat, levels: int) -> int:
    total = 0
    for lvl in range(levels):
        mw = max(1, w >> lvl)
        mh = max(1, h >> lvl)
        if mw >= 16 and mh >= 16:
            total += mip_data_size(mw, mh, fmt)
    return total


def _build_gtav(textures: list[Texture]) -> bytes:
    entries = sorted(textures, key=lambda t: _joaat(t.name))
    n = len(entries)
    if n == 0:
        raise ValueError("Cannot create texture dictionary with zero textures")

    # Virtual layout
    dict_size = 0x40
    keys_offset = dict_size
    ptrs_offset = _align(keys_offset + 4 * n, 16)
    textures_offset = _align(ptrs_offset + 8 * n, 16)

    cur = textures_offset + _GTAV_TEX_SIZE * n
    name_offsets: list[int] = []
    name_bytes_list: list[bytes] = []
    for e in entries:
        name_offsets.append(cur)
        encoded = e.name.encode("utf-8") + b"\x00"
        name_bytes_list.append(encoded)
        cur += len(encoded)

    pagemap_offset = _align(cur, 16)
    virtual_size = pagemap_offset + 0x10

    # Physical layout
    phys_offsets: list[int] = []
    phys_cur = 0
    for e in entries:
        phys_offsets.append(phys_cur)
        phys_cur += len(e.data)

    # Build virtual buffer
    vbuf = bytearray(virtual_size)

    struct.pack_into("<Q", vbuf, 0x00, 0)
    struct.pack_into("<Q", vbuf, 0x08, DAT_VIRTUAL_BASE + pagemap_offset)
    struct.pack_into("<Q", vbuf, 0x10, 0)
    struct.pack_into("<I", vbuf, 0x18, 1)
    struct.pack_into("<I", vbuf, 0x1C, 0)
    struct.pack_into("<Q", vbuf, 0x20, DAT_VIRTUAL_BASE + keys_offset)
    struct.pack_into("<HHI", vbuf, 0x28, n, n, 0)
    struct.pack_into("<Q", vbuf, 0x30, DAT_VIRTUAL_BASE + ptrs_offset)
    struct.pack_into("<HHI", vbuf, 0x38, n, n, 0)

    for i, e in enumerate(entries):
        struct.pack_into("<I", vbuf, keys_offset + 4 * i, _joaat(e.name))

    for i in range(n):
        tex_vaddr = DAT_VIRTUAL_BASE + textures_offset + _GTAV_TEX_SIZE * i
        struct.pack_into("<Q", vbuf, ptrs_offset + 8 * i, tex_vaddr)

    for i, e in enumerate(entries):
        off = textures_offset + _GTAV_TEX_SIZE * i
        format_val = BC_TO_DX9[e.format]
        stride = row_pitch(e.width, e.format)
        name_vaddr = DAT_VIRTUAL_BASE + name_offsets[i]
        data_paddr = DAT_PHYSICAL_BASE + phys_offsets[i]
        data_size_large = _large_mip_data_size(e.width, e.height, e.format, e.mip_count)

        struct.pack_into("<Q", vbuf, off + 0x00, 0)
        struct.pack_into("<q", vbuf, off + 0x08, 0)
        struct.pack_into("<q", vbuf, off + 0x10, 0)
        struct.pack_into("<Q", vbuf, off + 0x18, 0)
        struct.pack_into("<Q", vbuf, off + 0x20, 0)
        struct.pack_into("<Q", vbuf, off + 0x28, name_vaddr)
        struct.pack_into("<hbbiQ", vbuf, off + 0x30, 1, 0, 0, 0, 0)
        struct.pack_into("<I", vbuf, off + 0x40, data_size_large)
        struct.pack_into("<iihhhhI", vbuf, off + 0x44, 0, 0, 0, 0, e.width, e.height, 0)
        struct.pack_into("<hI", vbuf, off + 0x54, 1, 0)
        struct.pack_into("<h", vbuf, off + 0x56, stride)
        struct.pack_into("<I", vbuf, off + 0x58, format_val)
        struct.pack_into("<BBBB", vbuf, off + 0x5C, 0, e.mip_count, 0, 0)
        struct.pack_into("<QQ", vbuf, off + 0x60, 0, 0)
        struct.pack_into("<Q", vbuf, off + 0x70, data_paddr)
        struct.pack_into("<Qqq", vbuf, off + 0x78, 0, 0, 0)

    for i, name_data in enumerate(name_bytes_list):
        start = name_offsets[i]
        vbuf[start:start + len(name_data)] = name_data

    vbuf[pagemap_offset] = 1
    vbuf[pagemap_offset + 1] = 1

    pbuf = bytearray()
    for e in entries:
        pbuf.extend(e.data)

    return build_rsc7(bytes(vbuf), bytes(pbuf))


def _parse_gtav(file_data: bytes) -> ITD:
    virtual_data, physical_data = decompress_rsc7(file_data)

    count = _r_u16(virtual_data, 0x28)
    items_off = _v2o(_r_u64(virtual_data, 0x30))

    td = ITD(game=Game.GTA5)

    for i in range(count):
        tex_off = _v2o(_r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, _r_u64(virtual_data, tex_off + 0x28))
        width = _r_i16(virtual_data, tex_off + 0x50)
        height = _r_i16(virtual_data, tex_off + 0x52)
        format_val = _r_u32(virtual_data, tex_off + 0x58)
        mip_levels = _r_u8(virtual_data, tex_off + 0x5D)
        data_ptr = _r_u64(virtual_data, tex_off + 0x70)

        fmt = _resolve_gtav_format(format_val)
        if fmt is None:
            raise ValueError(f"Unsupported texture format: 0x{format_val:08X}")

        phys_off = _p2o(data_ptr)
        data_size = total_mip_data_size(width, height, fmt, mip_levels)
        pixel_data = physical_data[phys_off:phys_off + data_size]
        offsets, sizes = _build_mip_info(width, height, fmt, mip_levels)

        td.add(Texture.from_raw(pixel_data, width, height, fmt,
                                 mip_levels, offsets, sizes, name))

    return td


def _inspect_gtav(file_data: bytes) -> list[dict]:
    virtual_data, _ = decompress_rsc7(file_data)

    count = _r_u16(virtual_data, 0x28)
    items_off = _v2o(_r_u64(virtual_data, 0x30))

    result = []
    for i in range(count):
        tex_off = _v2o(_r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, _r_u64(virtual_data, tex_off + 0x28))
        width = _r_i16(virtual_data, tex_off + 0x50)
        height = _r_i16(virtual_data, tex_off + 0x52)
        format_val = _r_u32(virtual_data, tex_off + 0x58)
        mip_levels = _r_u8(virtual_data, tex_off + 0x5D)

        fmt = _resolve_gtav_format(format_val)
        data_size = total_mip_data_size(width, height, fmt, mip_levels) if fmt is not None else 0

        result.append({
            "name": name, "width": width, "height": height,
            "format": fmt,
            "format_name": fmt.name if fmt is not None else f"unknown(0x{format_val:08X})",
            "mip_count": mip_levels, "data_size": data_size,
        })

    return result


# ═════════════════════════════════════════════════════════════════════════════
# RDR2 (RSC8) internals
# ═════════════════════════════════════════════════════════════════════════════

_RDR2_TEX_SIZE = 0xB0  # 176 bytes

_RDR2_DICT_VFT      = 0x00000001409100B0
_RDR2_TEX_VFT       = 0x00000001409100B0
_RDR2_SRV_VFT       = 0x0000000140910080
_RDR2_FLAGS          = 0x18008002
_RDR2_TILE_STANDARD  = 13
_RDR2_DIM_2D         = 1
_RDR2_SRV_DIM_2D     = 0x0401


def _build_rdr2(textures: list[Texture]) -> bytes:
    entries = sorted(textures, key=lambda t: _joaat(t.name))
    n = len(entries)
    if n == 0:
        raise ValueError("Cannot create texture dictionary with zero textures")

    # Virtual layout
    dict_size = 64
    blockmap_off = _align(dict_size, 16)
    blockmap_size = 16 + 2 * 8  # 1 virtual + 1 physical page

    hash_off = _align(blockmap_off + blockmap_size, 16)
    ptr_off = _align(hash_off + n * 4, 16)
    tex_off_base = _align(ptr_off + n * 8, 16)

    cur = _align(tex_off_base + _RDR2_TEX_SIZE * n, 16)
    name_offsets: list[int] = []
    name_bytes_list: list[bytes] = []
    for e in entries:
        name_offsets.append(cur)
        encoded = e.name.encode("utf-8") + b"\x00"
        name_bytes_list.append(encoded)
        cur = _align(cur + len(encoded), 16)

    virtual_size = cur

    # Physical layout (padded to BlockCount * BlockStride)
    phys_offsets: list[int] = []
    phys_data_list: list[bytes] = []
    phys_cur = 0
    for e in entries:
        phys_offsets.append(phys_cur)
        bc = _block_count(e.format, e.width, e.height, 1, e.mip_count)
        target = bc * _block_stride(e.format)
        data = e.data if len(e.data) >= target else e.data + b"\x00" * (target - len(e.data))
        phys_data_list.append(data)
        phys_cur = _align(phys_cur + len(data), 16)

    physical_size = phys_cur

    # Page sizes for BlockMap
    v_page = _align(virtual_size, 0x10000 if virtual_size > 0x8000 else 16)
    p_page = _align(physical_size, 0x10000 if physical_size > 0x8000 else 16)

    # Build virtual buffer
    vbuf = bytearray(virtual_size)

    # Dictionary root (64 bytes)
    struct.pack_into("<Q", vbuf, 0x00, _RDR2_DICT_VFT)
    struct.pack_into("<Q", vbuf, 0x08, DAT_VIRTUAL_BASE + blockmap_off)
    struct.pack_into("<Q", vbuf, 0x10, 0)
    struct.pack_into("<Q", vbuf, 0x18, 1)
    struct.pack_into("<Q", vbuf, 0x20, DAT_VIRTUAL_BASE + hash_off)
    struct.pack_into("<HHI", vbuf, 0x28, n, n, 0)
    struct.pack_into("<Q", vbuf, 0x30, DAT_VIRTUAL_BASE + ptr_off)
    struct.pack_into("<HHI", vbuf, 0x38, n, n, 0)

    # BlockMap
    struct.pack_into("<QBBHI", vbuf, blockmap_off, 0, 1, 1, 0, 0)
    struct.pack_into("<QQ", vbuf, blockmap_off + 16, v_page, p_page)

    # Hash array
    for i, e in enumerate(entries):
        struct.pack_into("<I", vbuf, hash_off + 4 * i, _joaat(e.name))

    # Pointer array
    for i in range(n):
        struct.pack_into("<Q", vbuf, ptr_off + 8 * i,
                         DAT_VIRTUAL_BASE + tex_off_base + _RDR2_TEX_SIZE * i)

    # Texture blocks (176 bytes each)
    for i, e in enumerate(entries):
        off = tex_off_base + _RDR2_TEX_SIZE * i
        bc = _block_count(e.format, e.width, e.height, 1, e.mip_count)
        bs = _block_stride(e.format)

        # TextureBase (0x00–0x4F)
        struct.pack_into("<Q", vbuf, off + 0x00, _RDR2_TEX_VFT)
        struct.pack_into("<II", vbuf, off + 0x08, bc, bs)
        struct.pack_into("<II", vbuf, off + 0x10, _RDR2_FLAGS, 0)
        struct.pack_into("<HHH", vbuf, off + 0x18, e.width, e.height, 1)
        vbuf[off + 0x1E] = _RDR2_DIM_2D
        vbuf[off + 0x1F] = BC_TO_RSC8[e.format]
        vbuf[off + 0x20] = _RDR2_TILE_STANDARD
        vbuf[off + 0x21] = 0
        vbuf[off + 0x22] = e.mip_count
        struct.pack_into("<BBBH", vbuf, off + 0x23, 0, 0, 0, 1)  # unknowns + usage
        struct.pack_into("<Q", vbuf, off + 0x28, DAT_VIRTUAL_BASE + name_offsets[i])
        struct.pack_into("<Q", vbuf, off + 0x30, DAT_VIRTUAL_BASE + off + 0x68)  # SRV
        struct.pack_into("<Q", vbuf, off + 0x38, DAT_PHYSICAL_BASE + phys_offsets[i])
        struct.pack_into("<IIQ", vbuf, off + 0x40, 0, 0, 0)

        # Extended (0x50–0x67)
        struct.pack_into("<QQQ", vbuf, off + 0x50, 0, 0, 0)

        # Embedded SRV (0x68–0xA7)
        struct.pack_into("<QQ", vbuf, off + 0x68, _RDR2_SRV_VFT, 0)
        struct.pack_into("<QQ", vbuf, off + 0x78, _RDR2_SRV_DIM_2D, 5)
        struct.pack_into("<QQQQ", vbuf, off + 0x88, 0, 0, 0, 0)

        # Unknown_A8h
        struct.pack_into("<Q", vbuf, off + 0xA8, 0)

    # Name strings
    for i, name_data in enumerate(name_bytes_list):
        start = name_offsets[i]
        vbuf[start:start + len(name_data)] = name_data

    # Physical buffer
    pbuf = bytearray(physical_size)
    for i, data in enumerate(phys_data_list):
        pbuf[phys_offsets[i]:phys_offsets[i] + len(data)] = data

    return build_rsc8(bytes(vbuf), bytes(pbuf))


def _parse_rdr2(file_data: bytes) -> ITD:
    virtual_data, physical_data = decompress_rsc8(file_data)

    count = _r_u16(virtual_data, 0x28)
    items_off = _v2o(_r_u64(virtual_data, 0x30))

    td = ITD(game=Game.RDR2)

    for i in range(count):
        tex_off = _v2o(_r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, _r_u64(virtual_data, tex_off + 0x28))
        width = _r_u16(virtual_data, tex_off + 0x18)
        height = _r_u16(virtual_data, tex_off + 0x1A)
        format_byte = _r_u8(virtual_data, tex_off + 0x1F)
        mip_levels = _r_u8(virtual_data, tex_off + 0x22)
        data_ptr = _r_u64(virtual_data, tex_off + 0x38)

        fmt = RSC8_TO_BC.get(format_byte)
        if fmt is None:
            raise ValueError(f"Unsupported RSC8 format 0x{format_byte:02X} in '{name}'")

        phys_off = _p2o(data_ptr)
        data_size = total_mip_data_size(width, height, fmt, mip_levels)
        pixel_data = physical_data[phys_off:phys_off + data_size]
        offsets, sizes = _build_mip_info(width, height, fmt, mip_levels)

        td.add(Texture.from_raw(pixel_data, width, height, fmt,
                                 mip_levels, offsets, sizes, name))

    return td


def _inspect_rdr2(file_data: bytes) -> list[dict]:
    virtual_data, _ = decompress_rsc8(file_data)

    count = _r_u16(virtual_data, 0x28)
    items_off = _v2o(_r_u64(virtual_data, 0x30))

    result = []
    for i in range(count):
        tex_off = _v2o(_r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, _r_u64(virtual_data, tex_off + 0x28))
        width = _r_u16(virtual_data, tex_off + 0x18)
        height = _r_u16(virtual_data, tex_off + 0x1A)
        format_byte = _r_u8(virtual_data, tex_off + 0x1F)
        mip_levels = _r_u8(virtual_data, tex_off + 0x22)

        fmt = RSC8_TO_BC.get(format_byte)
        data_size = total_mip_data_size(width, height, fmt, mip_levels) if fmt is not None else 0

        result.append({
            "name": name, "width": width, "height": height,
            "format": fmt,
            "format_name": fmt.name if fmt is not None else f"unknown(0x{format_byte:02X})",
            "mip_count": mip_levels, "data_size": data_size,
        })

    return result


# ═════════════════════════════════════════════════════════════════════════════
# GTA V Enhanced / gen9 (RSC7 version 5) internals
# ═════════════════════════════════════════════════════════════════════════════

_ENHANCED_TEX_SIZE   = 0x80  # 128 bytes
_ENHANCED_FLAGS      = 0x00260208
_ENHANCED_TILE_AUTO  = 255
_ENHANCED_UNK_23H    = 0x28
_ENHANCED_UNK_44H    = 2
_ENHANCED_DIM_2D     = 1
_ENHANCED_SRV_VFT    = 0x00000001406B77D8
_ENHANCED_SRV_DIM_2D = 0x41
_RSC7_VERSION_GEN9   = 5


def _build_enhanced(textures: list[Texture]) -> bytes:
    entries = sorted(textures, key=lambda t: _joaat(t.name))
    n = len(entries)
    if n == 0:
        raise ValueError("Cannot create texture dictionary with zero textures")

    # Virtual layout (same dictionary header as legacy)
    dict_size = 0x40
    keys_offset = dict_size
    ptrs_offset = _align(keys_offset + 4 * n, 16)
    textures_offset = _align(ptrs_offset + 8 * n, 16)

    cur = textures_offset + _ENHANCED_TEX_SIZE * n
    name_offsets: list[int] = []
    name_bytes_list: list[bytes] = []
    for e in entries:
        name_offsets.append(cur)
        encoded = e.name.encode("utf-8") + b"\x00"
        name_bytes_list.append(encoded)
        cur += len(encoded)

    pagemap_offset = _align(cur, 16)
    virtual_size = pagemap_offset + 0x10

    # Physical layout — gen9 uses align=1 (no block padding)
    phys_offsets: list[int] = []
    phys_data_list: list[bytes] = []
    phys_cur = 0
    for e in entries:
        phys_offsets.append(phys_cur)
        bc = _block_count(e.format, e.width, e.height, 1, e.mip_count, align=1)
        target = bc * _block_stride(e.format)
        data = e.data if len(e.data) >= target else e.data + b"\x00" * (target - len(e.data))
        phys_data_list.append(data)
        phys_cur = _align(phys_cur + len(data), 16)

    physical_size = phys_cur

    # Build virtual buffer
    vbuf = bytearray(virtual_size)

    # Dictionary root (64 bytes)
    struct.pack_into("<Q", vbuf, 0x00, 0)  # VFT = 0
    struct.pack_into("<Q", vbuf, 0x08, DAT_VIRTUAL_BASE + pagemap_offset)
    struct.pack_into("<Q", vbuf, 0x10, 0)
    struct.pack_into("<I", vbuf, 0x18, 1)
    struct.pack_into("<I", vbuf, 0x1C, 0)
    struct.pack_into("<Q", vbuf, 0x20, DAT_VIRTUAL_BASE + keys_offset)
    struct.pack_into("<HHI", vbuf, 0x28, n, n, 0)
    struct.pack_into("<Q", vbuf, 0x30, DAT_VIRTUAL_BASE + ptrs_offset)
    struct.pack_into("<HHI", vbuf, 0x38, n, n, 0)

    # Hash array
    for i, e in enumerate(entries):
        struct.pack_into("<I", vbuf, keys_offset + 4 * i, _joaat(e.name))

    # Pointer array
    for i in range(n):
        tex_vaddr = DAT_VIRTUAL_BASE + textures_offset + _ENHANCED_TEX_SIZE * i
        struct.pack_into("<Q", vbuf, ptrs_offset + 8 * i, tex_vaddr)

    # Texture blocks (128 bytes each)
    for i, e in enumerate(entries):
        off = textures_offset + _ENHANCED_TEX_SIZE * i
        bc = _block_count(e.format, e.width, e.height, 1, e.mip_count, align=1)
        bs = _block_stride(e.format)

        # TextureBase (0x00–0x4F)
        struct.pack_into("<II", vbuf, off + 0x00, 0, 1)         # VFT=0, Unknown_4h=1
        struct.pack_into("<II", vbuf, off + 0x08, bc, bs)        # BlockCount, BlockStride
        struct.pack_into("<II", vbuf, off + 0x10, _ENHANCED_FLAGS, 0)
        struct.pack_into("<HHH", vbuf, off + 0x18, e.width, e.height, 1)  # W, H, Depth
        vbuf[off + 0x1E] = _ENHANCED_DIM_2D
        vbuf[off + 0x1F] = BC_TO_RSC8[e.format]                 # DXGI format byte
        vbuf[off + 0x20] = _ENHANCED_TILE_AUTO                  # TileMode = Auto (255)
        vbuf[off + 0x21] = 0                                    # AntiAliasType
        vbuf[off + 0x22] = e.mip_count
        vbuf[off + 0x23] = _ENHANCED_UNK_23H
        vbuf[off + 0x24] = 0
        vbuf[off + 0x25] = 0
        struct.pack_into("<H", vbuf, off + 0x26, 1)             # UsageCount
        struct.pack_into("<Q", vbuf, off + 0x28, DAT_VIRTUAL_BASE + name_offsets[i])
        struct.pack_into("<Q", vbuf, off + 0x30, DAT_VIRTUAL_BASE + off + 0x58)  # SRV ptr
        struct.pack_into("<Q", vbuf, off + 0x38, DAT_PHYSICAL_BASE + phys_offsets[i])
        struct.pack_into("<II", vbuf, off + 0x40, 0, _ENHANCED_UNK_44H)
        struct.pack_into("<Q", vbuf, off + 0x48, 0)

        # Texture extra (0x50–0x7F)
        struct.pack_into("<Q", vbuf, off + 0x50, 0)
        # Embedded ShaderResourceView (32 bytes at 0x58)
        struct.pack_into("<Q", vbuf, off + 0x58, _ENHANCED_SRV_VFT)
        struct.pack_into("<Q", vbuf, off + 0x60, 0)
        struct.pack_into("<HHI", vbuf, off + 0x68, _ENHANCED_SRV_DIM_2D, 0xFFFF, 0xFFFFFFFF)
        struct.pack_into("<Q", vbuf, off + 0x70, 0)
        struct.pack_into("<Q", vbuf, off + 0x78, 0)

    # Name strings
    for i, name_data in enumerate(name_bytes_list):
        start = name_offsets[i]
        vbuf[start:start + len(name_data)] = name_data

    # Pagemap (same as legacy)
    vbuf[pagemap_offset] = 1
    vbuf[pagemap_offset + 1] = 1

    # Physical buffer
    pbuf = bytearray(physical_size)
    for i, data in enumerate(phys_data_list):
        pbuf[phys_offsets[i]:phys_offsets[i] + len(data)] = data

    return build_rsc7(bytes(vbuf), bytes(pbuf), version=_RSC7_VERSION_GEN9)


def _parse_enhanced(file_data: bytes) -> ITD:
    virtual_data, physical_data = decompress_rsc7(file_data)

    count = _r_u16(virtual_data, 0x28)
    items_off = _v2o(_r_u64(virtual_data, 0x30))

    td = ITD(game=Game.GTA5_GEN9)

    for i in range(count):
        tex_off = _v2o(_r_u64(virtual_data, items_off + 8 * i))

        # Same field offsets as RDR2 texture base
        name = _read_name(virtual_data, _r_u64(virtual_data, tex_off + 0x28))
        width = _r_u16(virtual_data, tex_off + 0x18)
        height = _r_u16(virtual_data, tex_off + 0x1A)
        format_byte = _r_u8(virtual_data, tex_off + 0x1F)
        mip_levels = _r_u8(virtual_data, tex_off + 0x22)
        data_ptr = _r_u64(virtual_data, tex_off + 0x38)

        fmt = RSC8_TO_BC.get(format_byte)
        if fmt is None:
            raise ValueError(f"Unsupported gen9 format 0x{format_byte:02X} in '{name}'")

        phys_off = _p2o(data_ptr)
        data_size = total_mip_data_size(width, height, fmt, mip_levels)
        pixel_data = physical_data[phys_off:phys_off + data_size]
        offsets, sizes = _build_mip_info(width, height, fmt, mip_levels)

        td.add(Texture.from_raw(pixel_data, width, height, fmt,
                                 mip_levels, offsets, sizes, name))

    return td


def _inspect_enhanced(file_data: bytes) -> list[dict]:
    virtual_data, _ = decompress_rsc7(file_data)

    count = _r_u16(virtual_data, 0x28)
    items_off = _v2o(_r_u64(virtual_data, 0x30))

    result = []
    for i in range(count):
        tex_off = _v2o(_r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, _r_u64(virtual_data, tex_off + 0x28))
        width = _r_u16(virtual_data, tex_off + 0x18)
        height = _r_u16(virtual_data, tex_off + 0x1A)
        format_byte = _r_u8(virtual_data, tex_off + 0x1F)
        mip_levels = _r_u8(virtual_data, tex_off + 0x22)

        fmt = RSC8_TO_BC.get(format_byte)
        data_size = total_mip_data_size(width, height, fmt, mip_levels) if fmt is not None else 0

        result.append({
            "name": name, "width": width, "height": height,
            "format": fmt,
            "format_name": fmt.name if fmt is not None else f"unknown(0x{format_byte:02X})",
            "mip_count": mip_levels, "data_size": data_size,
        })

    return result


# ═════════════════════════════════════════════════════════════════════════════
# GTA IV (RSC5) internals — 32-bit pointers, .wtd files
# ═════════════════════════════════════════════════════════════════════════════

_GTA4_TEX_SIZE = 80      # bytes per texture struct
_GTA4_DICT_SIZE = 32     # bytes for dictionary header
_GTA4_BLOCKMAP_SIZE = 528  # 16 + 128 * 4

_V32 = 0x50000000
_P32 = 0x60000000


def _v2o32(addr: int) -> int:
    return addr - _V32


def _p2o32(addr: int) -> int:
    return addr - _P32


def _read_name_gta4(virtual_data: bytes, name_ptr: int) -> str:
    """Read a GTA4 name string (format: 'pack:/{name}.dds')."""
    off = _v2o32(name_ptr)
    end = virtual_data.index(b"\x00", off)
    raw = virtual_data[off:end].decode("utf-8", errors="replace")
    name = raw
    if name.startswith("pack:/"):
        name = name[6:]
    if name.endswith(".dds"):
        name = name[:-4]
    return name


def _build_gta4(textures: list[Texture]) -> bytes:
    entries = sorted(textures, key=lambda t: _joaat(t.name))
    n = len(entries)
    if n == 0:
        raise ValueError("Cannot create texture dictionary with zero textures")

    for e in entries:
        if e.format in _GTA4_UNSUPPORTED:
            raise ValueError(
                f"Format {e.format.name} is not supported by GTA IV. "
                f"Use BC1, BC3, or A8R8G8B8."
            )

    # Virtual layout — all 32-bit pointers
    blockmap_off = _GTA4_DICT_SIZE
    hash_off = _align(blockmap_off + _GTA4_BLOCKMAP_SIZE, 16)
    ptr_off = _align(hash_off + n * 4, 16)
    tex_off_base = _align(ptr_off + n * 4, 16)

    cur = tex_off_base + _GTA4_TEX_SIZE * n
    name_offsets: list[int] = []
    name_bytes_list: list[bytes] = []
    for e in entries:
        name_offsets.append(cur)
        encoded = f"pack:/{e.name}.dds".encode("utf-8") + b"\x00"
        name_bytes_list.append(encoded)
        cur += len(encoded)

    virtual_size = _align(cur, 16)

    # Physical layout
    phys_offsets: list[int] = []
    phys_cur = 0
    for e in entries:
        phys_offsets.append(phys_cur)
        phys_cur += len(e.data)

    # Build virtual buffer
    vbuf = bytearray(virtual_size)

    # Dictionary (32 bytes)
    struct.pack_into("<I", vbuf, 0x00, 0)                    # VFT
    struct.pack_into("<I", vbuf, 0x04, _V32 + blockmap_off)  # BlockMap ptr
    struct.pack_into("<I", vbuf, 0x08, 0)                    # ParentDictionary
    struct.pack_into("<I", vbuf, 0x0C, 1)                    # UsageCount
    struct.pack_into("<I", vbuf, 0x10, _V32 + hash_off)      # Hash array ptr
    struct.pack_into("<HH", vbuf, 0x14, n, n)                # count, capacity
    struct.pack_into("<I", vbuf, 0x18, _V32 + ptr_off)       # Textures ptr array ptr
    struct.pack_into("<HH", vbuf, 0x1C, n, n)                # count, capacity

    # BlockMap (528 bytes = 16 header + 128 * 4 padding)
    struct.pack_into("<I", vbuf, blockmap_off + 0x00, 0)
    for bm_i in range(1, 132):  # entries 1-131 = 0xCDCDCDCD
        struct.pack_into("<I", vbuf, blockmap_off + bm_i * 4, 0xCDCDCDCD)

    # Hash array
    for i, e in enumerate(entries):
        struct.pack_into("<I", vbuf, hash_off + 4 * i, _joaat(e.name))

    # Pointer array (uint32)
    for i in range(n):
        struct.pack_into("<I", vbuf, ptr_off + 4 * i,
                         _V32 + tex_off_base + _GTA4_TEX_SIZE * i)

    # Texture blocks (80 bytes each)
    for i, e in enumerate(entries):
        off = tex_off_base + _GTA4_TEX_SIZE * i
        format_val = BC_TO_RSC5[e.format]
        # Stride = width * bits_per_pixel / 8
        bpp = {BCFormat.BC1: 4, BCFormat.BC3: 8, BCFormat.A8R8G8B8: 32}[e.format]
        stride = e.width * bpp // 8

        # TextureBase (28 bytes)
        struct.pack_into("<II", vbuf, off + 0x00, 0, 0)       # VFT, Unknown1
        struct.pack_into("<HH", vbuf, off + 0x08, 1, 0)       # Unknown2=1, Unknown3=0
        struct.pack_into("<II", vbuf, off + 0x0C, 0, 0)       # Unknown4, Unknown5
        struct.pack_into("<I", vbuf, off + 0x14, _V32 + name_offsets[i])
        struct.pack_into("<I", vbuf, off + 0x18, 0)           # Unknown6

        # Texture-specific (52 bytes)
        struct.pack_into("<HH", vbuf, off + 0x1C, e.width, e.height)
        struct.pack_into("<I", vbuf, off + 0x20, format_val)
        struct.pack_into("<H", vbuf, off + 0x24, stride)
        vbuf[off + 0x26] = 0                                   # TextureType
        vbuf[off + 0x27] = e.mip_count
        struct.pack_into("<ffffff", vbuf, off + 0x28,
                         1.0, 1.0, 1.0, 0.0, 0.0, 0.0)       # Unknown7–12
        struct.pack_into("<II", vbuf, off + 0x40, 0, 0)       # Prev/Next
        struct.pack_into("<I", vbuf, off + 0x48, _P32 + phys_offsets[i])
        struct.pack_into("<I", vbuf, off + 0x4C, 0)           # Unknown13

    # Name strings
    for i, name_data in enumerate(name_bytes_list):
        start = name_offsets[i]
        vbuf[start:start + len(name_data)] = name_data

    # Physical buffer
    pbuf = bytearray()
    for e in entries:
        pbuf.extend(e.data)

    return build_rsc5(bytes(vbuf), bytes(pbuf))


def _parse_gta4(file_data: bytes) -> ITD:
    virtual_data, physical_data = decompress_rsc5(file_data)

    count = _r_u16(virtual_data, 0x14)
    ptr_arr_off = _v2o32(_r_u32(virtual_data, 0x18))

    td = ITD(game=Game.GTA4)

    for i in range(count):
        tex_off = _v2o32(_r_u32(virtual_data, ptr_arr_off + 4 * i))

        name = _read_name_gta4(virtual_data, _r_u32(virtual_data, tex_off + 0x14))
        width = _r_u16(virtual_data, tex_off + 0x1C)
        height = _r_u16(virtual_data, tex_off + 0x1E)
        format_val = _r_u32(virtual_data, tex_off + 0x20)
        mip_levels = virtual_data[tex_off + 0x27]
        data_ptr = _r_u32(virtual_data, tex_off + 0x48)

        fmt = RSC5_TO_BC.get(format_val)
        if fmt is None:
            raise ValueError(f"Unsupported RSC5 format 0x{format_val:08X} in '{name}'")

        phys_off = _p2o32(data_ptr)
        data_size = total_mip_data_size(width, height, fmt, mip_levels)
        pixel_data = physical_data[phys_off:phys_off + data_size]
        offsets, sizes = _build_mip_info(width, height, fmt, mip_levels)

        td.add(Texture.from_raw(pixel_data, width, height, fmt,
                                 mip_levels, offsets, sizes, name))

    return td


def _inspect_gta4(file_data: bytes) -> list[dict]:
    virtual_data, _ = decompress_rsc5(file_data)

    count = _r_u16(virtual_data, 0x14)
    ptr_arr_off = _v2o32(_r_u32(virtual_data, 0x18))

    result = []
    for i in range(count):
        tex_off = _v2o32(_r_u32(virtual_data, ptr_arr_off + 4 * i))

        name = _read_name_gta4(virtual_data, _r_u32(virtual_data, tex_off + 0x14))
        width = _r_u16(virtual_data, tex_off + 0x1C)
        height = _r_u16(virtual_data, tex_off + 0x1E)
        format_val = _r_u32(virtual_data, tex_off + 0x20)
        mip_levels = virtual_data[tex_off + 0x27]

        fmt = RSC5_TO_BC.get(format_val)
        data_size = total_mip_data_size(width, height, fmt, mip_levels) if fmt is not None else 0

        result.append({
            "name": name, "width": width, "height": height,
            "format": fmt,
            "format_name": fmt.name if fmt is not None else f"unknown(0x{format_val:08X})",
            "mip_count": mip_levels, "data_size": data_size,
        })

    return result
