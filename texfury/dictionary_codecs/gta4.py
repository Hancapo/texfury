"""GTA IV RSC5 texture dictionary codec."""

import struct

from texfury.binary import align, joaat, r_u16, r_u32
from texfury.formats import (
    BCFormat, BC_TO_RSC5, RSC5_TO_BC, _GTA4_UNSUPPORTED,
    total_mip_data_size,
)
from texfury.rsc import build_rsc5, decompress_rsc5
from texfury.texture import Texture
from texfury.dictionary_codecs.common import _build_mip_info, _slice_texture_data
from texfury.texture_dict import Game, ITD

# ═════════════════════════════════════════════════════════════════════════════
# GTA IV (RSC5) internals — 32-bit pointers, .wtd files
# ═════════════════════════════════════════════════════════════════════════════

_GTA4_TEX_SIZE = 80      # bytes per texture struct
_GTA4_DICT_SIZE = 32     # bytes for dictionary header
_GTA4_BLOCKMAP_SIZE = 528  # 16 + 128 * 4

_V32 = 0x50000000
_P32 = 0x60000000


def v2o32(addr: int) -> int:
    return addr - _V32


def p2o32(addr: int) -> int:
    return addr - _P32


def _read_name_gta4(virtual_data: bytes, name_ptr: int) -> str:
    """Read a GTA4 name string (format: 'pack:/{name}.dds')."""
    off = v2o32(name_ptr)
    end = virtual_data.index(b"\x00", off)
    raw = virtual_data[off:end].decode("utf-8", errors="replace")
    name = raw
    if name.startswith("pack:/"):
        name = name[6:]
    if name.endswith(".dds"):
        name = name[:-4]
    return name


def _build_gta4(textures: list[Texture]) -> bytes:
    entries = sorted(textures, key=lambda t: joaat(t.name))
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
    hash_off = align(blockmap_off + _GTA4_BLOCKMAP_SIZE, 16)
    ptr_off = align(hash_off + n * 4, 16)
    tex_off_base = align(ptr_off + n * 4, 16)

    cur = tex_off_base + _GTA4_TEX_SIZE * n
    name_offsets: list[int] = []
    name_bytes_list: list[bytes] = []
    for e in entries:
        name_offsets.append(cur)
        encoded = f"pack:/{e.name}.dds".encode("utf-8") + b"\x00"
        name_bytes_list.append(encoded)
        cur += len(encoded)

    virtual_size = align(cur, 16)

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
        struct.pack_into("<I", vbuf, hash_off + 4 * i, joaat(e.name))

    # Pointer array (uint32)
    for i in range(n):
        struct.pack_into("<I", vbuf, ptr_off + 4 * i,
                         _V32 + tex_off_base + _GTA4_TEX_SIZE * i)

    # Texture blocks (80 bytes each)
    for i, e in enumerate(entries):
        off = tex_off_base + _GTA4_TEX_SIZE * i
        format_val = BC_TO_RSC5[e.format]
        # Stride = width * bits_per_pixel / 8
        bpp = {
            BCFormat.BC1: 4,
            BCFormat.BC1A: 4,
            BCFormat.BC3: 8,
            BCFormat.A8R8G8B8: 32,
        }[e.format]
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

    count = r_u16(virtual_data, 0x14)
    ptr_arr_off = v2o32(r_u32(virtual_data, 0x18))

    td = ITD(game=Game.GTA4)

    for i in range(count):
        tex_off = v2o32(r_u32(virtual_data, ptr_arr_off + 4 * i))

        name = _read_name_gta4(virtual_data, r_u32(virtual_data, tex_off + 0x14))
        width = r_u16(virtual_data, tex_off + 0x1C)
        height = r_u16(virtual_data, tex_off + 0x1E)
        format_val = r_u32(virtual_data, tex_off + 0x20)
        mip_levels = virtual_data[tex_off + 0x27]
        data_ptr = r_u32(virtual_data, tex_off + 0x48)

        fmt = RSC5_TO_BC.get(format_val)
        if fmt is None:
            raise ValueError(f"Unsupported RSC5 format 0x{format_val:08X} in '{name}'")

        phys_off = p2o32(data_ptr)
        data_size = total_mip_data_size(width, height, fmt, mip_levels)
        pixel_data = _slice_texture_data(
            physical_data, phys_off, data_size, name=name,
            width=width, height=height, mip_levels=mip_levels,
        )
        offsets, sizes = _build_mip_info(width, height, fmt, mip_levels)

        td.add(Texture.from_raw(pixel_data, width, height, fmt,
                                 mip_levels, offsets, sizes, name))

    return td


def _inspect_gta4(file_data: bytes) -> list[dict]:
    virtual_data, _ = decompress_rsc5(file_data)

    count = r_u16(virtual_data, 0x14)
    ptr_arr_off = v2o32(r_u32(virtual_data, 0x18))

    result = []
    for i in range(count):
        tex_off = v2o32(r_u32(virtual_data, ptr_arr_off + 4 * i))

        name = _read_name_gta4(virtual_data, r_u32(virtual_data, tex_off + 0x14))
        width = r_u16(virtual_data, tex_off + 0x1C)
        height = r_u16(virtual_data, tex_off + 0x1E)
        format_val = r_u32(virtual_data, tex_off + 0x20)
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
