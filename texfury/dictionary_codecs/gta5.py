"""GTA V legacy RSC7 texture dictionary codec."""

import struct

from texfury.binary import align, joaat, r_i16, r_u8, r_u16, r_u32, r_u64
from texfury.formats import (
    BCFormat, BC_TO_DX9, DX9_TO_BC, DXGI_TO_BC, FOURCC_TO_BC,
    mip_data_size, row_pitch, total_mip_data_size,
)
from texfury.rsc import (
    DAT_PHYSICAL_BASE, DAT_VIRTUAL_BASE, build_rsc7, decompress_rsc7,
)
from texfury.texture import Texture
from texfury.dictionary_codecs.common import (
    _build_mip_info, _read_name, _slice_texture_data, p2o, v2o,
)
from texfury.texture_dict import Game, ITD

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
    entries = sorted(textures, key=lambda t: joaat(t.name))
    n = len(entries)
    if n == 0:
        raise ValueError("Cannot create texture dictionary with zero textures")

    # Virtual layout
    dict_size = 0x40
    keys_offset = dict_size
    ptrs_offset = align(keys_offset + 4 * n, 16)
    textures_offset = align(ptrs_offset + 8 * n, 16)

    cur = textures_offset + _GTAV_TEX_SIZE * n
    name_offsets: list[int] = []
    name_bytes_list: list[bytes] = []
    for e in entries:
        name_offsets.append(cur)
        encoded = e.name.encode("utf-8") + b"\x00"
        name_bytes_list.append(encoded)
        cur += len(encoded)

    pagemap_offset = align(cur, 16)
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
        struct.pack_into("<I", vbuf, keys_offset + 4 * i, joaat(e.name))

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

    count = r_u16(virtual_data, 0x28)
    items_off = v2o(r_u64(virtual_data, 0x30))

    td = ITD(game=Game.GTA5)

    for i in range(count):
        tex_off = v2o(r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, r_u64(virtual_data, tex_off + 0x28))
        width = r_i16(virtual_data, tex_off + 0x50)
        height = r_i16(virtual_data, tex_off + 0x52)
        format_val = r_u32(virtual_data, tex_off + 0x58)
        mip_levels = r_u8(virtual_data, tex_off + 0x5D)
        data_ptr = r_u64(virtual_data, tex_off + 0x70)

        fmt = _resolve_gtav_format(format_val)
        if fmt is None:
            raise ValueError(f"Unsupported texture format: 0x{format_val:08X}")

        phys_off = p2o(data_ptr)
        data_size = total_mip_data_size(width, height, fmt, mip_levels)
        pixel_data = _slice_texture_data(
            physical_data, phys_off, data_size, name=name,
            width=width, height=height, mip_levels=mip_levels,
        )
        offsets, sizes = _build_mip_info(width, height, fmt, mip_levels)

        td.add(Texture.from_raw(pixel_data, width, height, fmt,
                                 mip_levels, offsets, sizes, name))

    return td


def _inspect_gtav(file_data: bytes) -> list[dict]:
    virtual_data, _ = decompress_rsc7(file_data)

    count = r_u16(virtual_data, 0x28)
    items_off = v2o(r_u64(virtual_data, 0x30))

    result = []
    for i in range(count):
        tex_off = v2o(r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, r_u64(virtual_data, tex_off + 0x28))
        width = r_i16(virtual_data, tex_off + 0x50)
        height = r_i16(virtual_data, tex_off + 0x52)
        format_val = r_u32(virtual_data, tex_off + 0x58)
        mip_levels = r_u8(virtual_data, tex_off + 0x5D)

        fmt = _resolve_gtav_format(format_val)
        data_size = total_mip_data_size(width, height, fmt, mip_levels) if fmt is not None else 0

        result.append({
            "name": name, "width": width, "height": height,
            "format": fmt,
            "format_name": fmt.name if fmt is not None else f"unknown(0x{format_val:08X})",
            "mip_count": mip_levels, "data_size": data_size,
        })

    return result
