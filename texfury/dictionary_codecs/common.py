"""Shared binary helpers for RAGE texture dictionary codecs."""

import struct

from texfury.formats import BCFormat, is_block_compressed, mip_data_size
from texfury.rsc import DAT_PHYSICAL_BASE, DAT_VIRTUAL_BASE, parse_rsc7_header
from texfury.rsc.rsc7 import (
    _deflate_decompress as _rsc7_deflate_decompress,
    total_from_flags as _rsc7_total_from_flags,
)

def v2o(addr: int) -> int: return addr - DAT_VIRTUAL_BASE

def p2o(addr: int) -> int: return addr - DAT_PHYSICAL_BASE

def _r_be_u16(d: bytes, o: int) -> int: return struct.unpack_from(">H", d, o)[0]

def _r_be_u32(d: bytes, o: int) -> int: return struct.unpack_from(">I", d, o)[0]

def _slice_texture_data(physical_data: bytes, phys_off: int, data_size: int,
                        *, name: str, width: int, height: int,
                        mip_levels: int) -> bytes:
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid dimensions for '{name}': {width}x{height}")
    if mip_levels < 1:
        raise ValueError(f"Invalid mip count for '{name}': {mip_levels}")
    if phys_off < 0 or data_size < 0 or phys_off + data_size > len(physical_data):
        raise ValueError(
            f"Texture data for '{name}' is outside the physical buffer "
            f"(offset={phys_off}, size={data_size}, buffer={len(physical_data)})"
        )
    return physical_data[phys_off:phys_off + data_size]

def _decompress_rsc7_padded(data: bytes) -> tuple[bytes, bytes]:
    """Decompress RSC7 and zero-fill sparse PS3-style page tails."""
    _, sys_flags, gfx_flags = parse_rsc7_header(data)
    sys_size = _rsc7_total_from_flags(sys_flags & 0x0FFFFFFF)
    gfx_size = _rsc7_total_from_flags(gfx_flags & 0x0FFFFFFF)
    raw = _rsc7_deflate_decompress(data[16:])
    raw = raw[:sys_size + gfx_size].ljust(sys_size + gfx_size, b"\x00")
    return raw[:sys_size], raw[sys_size:sys_size + gfx_size]

def _looks_like_gtav_ps3_virtual(virtual_data: bytes) -> bool:
    if len(virtual_data) < 0x20:
        return False
    if _r_be_u32(virtual_data, 0x00) != 0xE0678100:
        return False

    hash_ptr = _r_be_u32(virtual_data, 0x10)
    item_ptr = _r_be_u32(virtual_data, 0x18)
    hash_count = _r_be_u16(virtual_data, 0x14)
    item_count = _r_be_u16(virtual_data, 0x1C)
    if hash_count != item_count or item_count > 4096:
        return False
    return (
        DAT_VIRTUAL_BASE <= hash_ptr < DAT_VIRTUAL_BASE + len(virtual_data) and
        DAT_VIRTUAL_BASE <= item_ptr < DAT_VIRTUAL_BASE + len(virtual_data)
    )

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
    name_off = v2o(name_ptr)
    name_end = virtual_data.index(b"\x00", name_off)
    return virtual_data[name_off:name_end].decode("utf-8", errors="replace")

def _block_stride(fmt: BCFormat) -> int:
    """Block stride in bytes. Used by RDR2 and GTA V Enhanced."""
    if fmt in (BCFormat.BC1, BCFormat.BC1A, BCFormat.BC4):
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
