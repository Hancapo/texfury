"""RDR2 RSC8 texture dictionary codec."""

import struct

from texfury.binary import align, joaat, r_u8, r_u16, r_u64
from texfury.formats import (
    BC_TO_RSC8, RSC8_TO_BC, RscCompression, total_mip_data_size,
)
from texfury.rsc import (
    DAT_PHYSICAL_BASE, DAT_VIRTUAL_BASE, build_rsc8, decompress_rsc8,
)
from texfury.texture import Texture
from texfury.dictionary_codecs.common import (
    _block_count, _block_stride, _build_mip_info, _read_name,
    _slice_texture_data, p2o, v2o,
)
from texfury.texture_dict import Game, ITD

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


def _build_rdr2(textures: list[Texture], compression: RscCompression = RscCompression.OODLE) -> bytes:
    entries = sorted(textures, key=lambda t: joaat(t.name))
    n = len(entries)
    if n == 0:
        raise ValueError("Cannot create texture dictionary with zero textures")

    # Virtual layout
    dict_size = 64
    blockmap_off = align(dict_size, 16)
    blockmap_size = 16 + 2 * 8  # 1 virtual + 1 physical page

    hash_off = align(blockmap_off + blockmap_size, 16)
    ptr_off = align(hash_off + n * 4, 16)
    tex_off_base = align(ptr_off + n * 8, 16)

    cur = align(tex_off_base + _RDR2_TEX_SIZE * n, 16)
    name_offsets: list[int] = []
    name_bytes_list: list[bytes] = []
    for e in entries:
        name_offsets.append(cur)
        encoded = e.name.encode("utf-8") + b"\x00"
        name_bytes_list.append(encoded)
        cur = align(cur + len(encoded), 16)

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
        phys_cur = align(phys_cur + len(data), 16)

    physical_size = phys_cur

    # Page sizes for BlockMap
    v_page = align(virtual_size, 0x10000 if virtual_size > 0x8000 else 16)
    p_page = align(physical_size, 0x10000 if physical_size > 0x8000 else 16)

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
        struct.pack_into("<I", vbuf, hash_off + 4 * i, joaat(e.name))

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

    return build_rsc8(bytes(vbuf), bytes(pbuf), compression=compression)


def _parse_rdr2(file_data: bytes) -> ITD:
    virtual_data, physical_data = decompress_rsc8(file_data)

    count = r_u16(virtual_data, 0x28)
    items_off = v2o(r_u64(virtual_data, 0x30))

    td = ITD(game=Game.RDR2)

    for i in range(count):
        tex_off = v2o(r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, r_u64(virtual_data, tex_off + 0x28))
        width = r_u16(virtual_data, tex_off + 0x18)
        height = r_u16(virtual_data, tex_off + 0x1A)
        format_byte = r_u8(virtual_data, tex_off + 0x1F)
        mip_levels = r_u8(virtual_data, tex_off + 0x22)
        data_ptr = r_u64(virtual_data, tex_off + 0x38)

        fmt = RSC8_TO_BC.get(format_byte)
        if fmt is None:
            raise ValueError(f"Unsupported RSC8 format 0x{format_byte:02X} in '{name}'")

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


def _inspect_rdr2(file_data: bytes) -> list[dict]:
    virtual_data, _ = decompress_rsc8(file_data)

    count = r_u16(virtual_data, 0x28)
    items_off = v2o(r_u64(virtual_data, 0x30))

    result = []
    for i in range(count):
        tex_off = v2o(r_u64(virtual_data, items_off + 8 * i))

        name = _read_name(virtual_data, r_u64(virtual_data, tex_off + 0x28))
        width = r_u16(virtual_data, tex_off + 0x18)
        height = r_u16(virtual_data, tex_off + 0x1A)
        format_byte = r_u8(virtual_data, tex_off + 0x1F)
        mip_levels = r_u8(virtual_data, tex_off + 0x22)

        fmt = RSC8_TO_BC.get(format_byte)
        data_size = total_mip_data_size(width, height, fmt, mip_levels) if fmt is not None else 0

        result.append({
            "name": name, "width": width, "height": height,
            "format": fmt,
            "format_name": fmt.name if fmt is not None else f"unknown(0x{format_byte:02X})",
            "mip_count": mip_levels, "data_size": data_size,
        })

    return result
