"""GTA V Enhanced RSC7 texture dictionary codec."""

import struct

from texfury.binary import align, joaat, r_u8, r_u16, r_u64
from texfury.formats import BC_TO_RSC8, RSC8_TO_BC, total_mip_data_size
from texfury.rsc import (
    DAT_PHYSICAL_BASE, DAT_VIRTUAL_BASE, build_rsc7, decompress_rsc7,
)
from texfury.texture import Texture
from texfury.dictionary_codecs.common import (
    _block_count, _block_stride, _build_mip_info, _read_name,
    _slice_texture_data, p2o, v2o,
)
from texfury.texture_dict import Game, ITD

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
    entries = sorted(textures, key=lambda t: joaat(t.name))
    n = len(entries)
    if n == 0:
        raise ValueError("Cannot create texture dictionary with zero textures")

    # Virtual layout (same dictionary header as legacy)
    dict_size = 0x40
    keys_offset = dict_size
    ptrs_offset = align(keys_offset + 4 * n, 16)
    textures_offset = align(ptrs_offset + 8 * n, 16)

    cur = textures_offset + _ENHANCED_TEX_SIZE * n
    name_offsets: list[int] = []
    name_bytes_list: list[bytes] = []
    for e in entries:
        name_offsets.append(cur)
        encoded = e.name.encode("utf-8") + b"\x00"
        name_bytes_list.append(encoded)
        cur += len(encoded)

    pagemap_offset = align(cur, 16)
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
        phys_cur = align(phys_cur + len(data), 16)

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
        struct.pack_into("<I", vbuf, keys_offset + 4 * i, joaat(e.name))

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

    count = r_u16(virtual_data, 0x28)
    items_off = v2o(r_u64(virtual_data, 0x30))

    td = ITD(game=Game.GTA5_GEN9)

    for i in range(count):
        tex_off = v2o(r_u64(virtual_data, items_off + 8 * i))

        # Same field offsets as RDR2 texture base
        name = _read_name(virtual_data, r_u64(virtual_data, tex_off + 0x28))
        width = r_u16(virtual_data, tex_off + 0x18)
        height = r_u16(virtual_data, tex_off + 0x1A)
        format_byte = r_u8(virtual_data, tex_off + 0x1F)
        mip_levels = r_u8(virtual_data, tex_off + 0x22)
        data_ptr = r_u64(virtual_data, tex_off + 0x38)

        fmt = RSC8_TO_BC.get(format_byte)
        if fmt is None:
            raise ValueError(f"Unsupported gen9 format 0x{format_byte:02X} in '{name}'")

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


def _inspect_enhanced(file_data: bytes) -> list[dict]:
    virtual_data, _ = decompress_rsc7(file_data)

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
