"""GTA V PS3 CTD texture dictionary codec."""

from texfury.formats import (
    BCFormat, is_block_compressed, mip_data_size, pixel_byte_size,
)
from texfury.texture import Texture
from texfury.dictionary_codecs.common import (
    _decompress_rsc7_padded, _looks_like_gtav_ps3_virtual,
    _r_be_u16, _r_be_u32, p2o, v2o,
)
from texfury.texture_dict import Game, ITD

# ═════════════════════════════════════════════════════════════════════════════
# GTA V PS3 / CTD (RSC7 + GCM) internals
# ═════════════════════════════════════════════════════════════════════════════

_GCM_FORMATS: dict[int, BCFormat] = {
    0x81: BCFormat.R8,          # CELL_GCM_TEXTURE_B8
    0x85: BCFormat.A8R8G8B8,    # CELL_GCM_TEXTURE_A8R8G8B8
    0x86: BCFormat.BC1,         # CELL_GCM_TEXTURE_COMPRESSED_DXT1
    0x87: BCFormat.BC2,         # CELL_GCM_TEXTURE_COMPRESSED_DXT23
    0x88: BCFormat.BC3,         # CELL_GCM_TEXTURE_COMPRESSED_DXT45
}

_GCM_TEXTURE_LN = 0x20


def _strip_gcm_texture_format(format_byte: int) -> int:
    # Matches grcore::gcm::StripTextureFormat for the common PS3 texture flags.
    return format_byte & 0x9F


def _gcm_swizzle_masks(width: int, height: int) -> tuple[int, int]:
    """Build the RSX Morton-coordinate masks used by RAGE."""
    mask_x = 0
    mask_y = 0
    dimension_bit = 1
    address_bit = 1
    while dimension_bit < width or dimension_bit < height:
        if dimension_bit < width:
            mask_x |= address_bit
            address_bit <<= 1
        if dimension_bit < height:
            mask_y |= address_bit
            address_bit <<= 1
        dimension_bit <<= 1
    return mask_x, mask_y


def _gcm_swizzle_component(value: int, mask: int) -> int:
    result = 0
    bit = 1
    while bit <= mask:
        if mask & bit:
            result |= value & bit
        else:
            value <<= 1
        bit <<= 1
    return result


def _unswizzle_gcm_mip(data: bytes, width: int, height: int,
                        bytes_per_pixel: int) -> bytes:
    """Convert an RSX Morton/Z-order mip to tightly packed row-major data."""
    if (width & (width - 1)) or (height & (height - 1)):
        raise ValueError(
            f"Swizzled GCM mip dimensions must be powers of two: {width}x{height}"
        )

    mask_x, mask_y = _gcm_swizzle_masks(width, height)
    x_offsets = [_gcm_swizzle_component(x, mask_x) for x in range(width)]
    y_offsets = [_gcm_swizzle_component(y, mask_y) for y in range(height)]
    output = bytearray(len(data))

    for y, y_offset in enumerate(y_offsets):
        row_offset = y * width * bytes_per_pixel
        for x, x_offset in enumerate(x_offsets):
            source = (x_offset | y_offset) * bytes_per_pixel
            destination = row_offset + x * bytes_per_pixel
            output[destination:destination + bytes_per_pixel] = \
                data[source:source + bytes_per_pixel]
    return bytes(output)


def _normalize_gcm_mip(data: bytes, width: int, height: int,
                       fmt: BCFormat, format_byte: int) -> bytes:
    """Convert an uncompressed PS3 mip to the byte layout expected by DDS."""
    if is_block_compressed(fmt):
        return data

    bytes_per_pixel = pixel_byte_size(fmt)
    if not format_byte & _GCM_TEXTURE_LN:
        data = _unswizzle_gcm_mip(data, width, height, bytes_per_pixel)

    if fmt == BCFormat.A8R8G8B8:
        # RSX stores the big-endian A8R8G8B8 word as ARGB bytes. DDS uses BGRA.
        converted = bytearray(len(data))
        for offset in range(0, len(data), 4):
            converted[offset:offset + 4] = data[offset:offset + 4][::-1]
        return bytes(converted)
    return data


def _read_be_name(virtual_data: bytes, name_ptr: int) -> str:
    name_off = v2o(name_ptr)
    if name_off < 0 or name_off >= len(virtual_data):
        raise ValueError(f"Texture name pointer outside virtual buffer: 0x{name_ptr:08X}")
    name_end = virtual_data.index(b"\x00", name_off)
    return virtual_data[name_off:name_end].decode("utf-8", errors="replace")


def _parse_gtav_ps3_entries(file_data: bytes, *, include_data: bool) -> list[dict]:
    virtual_data, physical_data = _decompress_rsc7_padded(file_data)
    if not _looks_like_gtav_ps3_virtual(virtual_data):
        raise ValueError("Not a GTA V PS3 CTD texture dictionary")

    count = _r_be_u16(virtual_data, 0x1C)
    items_off = v2o(_r_be_u32(virtual_data, 0x18))
    if items_off < 0 or items_off + count * 4 > len(virtual_data):
        raise ValueError("GTA V PS3 CTD texture pointer array is outside the virtual buffer")

    entries: list[dict] = []
    for i in range(count):
        tex_ptr = _r_be_u32(virtual_data, items_off + 4 * i)
        tex_off = v2o(tex_ptr)
        if tex_off < 0 or tex_off + 0x38 > len(virtual_data):
            raise ValueError(f"GTA V PS3 CTD texture {i} is outside the virtual buffer")

        format_byte = virtual_data[tex_off + 0x08]
        format_val = _strip_gcm_texture_format(format_byte)
        fmt = _GCM_FORMATS.get(format_val)
        if fmt is None:
            raise ValueError(f"Unsupported GTA V PS3 GCM texture format: 0x{format_val:02X}")

        mip_levels = virtual_data[tex_off + 0x09]
        dimension = virtual_data[tex_off + 0x0A]
        cubemap = virtual_data[tex_off + 0x0B]
        width = _r_be_u16(virtual_data, tex_off + 0x10)
        height = _r_be_u16(virtual_data, tex_off + 0x12)
        depth = _r_be_u16(virtual_data, tex_off + 0x14)
        data_ptr = _r_be_u32(virtual_data, tex_off + 0x1C)
        name = _read_be_name(virtual_data, _r_be_u32(virtual_data, tex_off + 0x20))
        mip_offsets_ptr = _r_be_u32(virtual_data, tex_off + 0x34)
        mip_offsets_off = v2o(mip_offsets_ptr)

        if dimension != 2 or cubemap != 0 or depth not in (0, 1):
            raise ValueError(
                f"Unsupported GTA V PS3 texture shape for '{name}': "
                f"dimension={dimension}, cubemap={cubemap}, depth={depth}"
            )
        if mip_levels < 1:
            raise ValueError(f"Invalid mip count for '{name}': {mip_levels}")
        if mip_offsets_off < 0 or mip_offsets_off + mip_levels * 4 > len(virtual_data):
            raise ValueError(f"Mip offset table for '{name}' is outside the virtual buffer")

        data_base = p2o(data_ptr)
        if data_base < 0 or data_base > len(physical_data):
            raise ValueError(f"Texture data pointer for '{name}' is outside the physical buffer")

        source_offsets = [_r_be_u32(virtual_data, mip_offsets_off + 4 * m) for m in range(mip_levels)]
        packed_offsets: list[int] = []
        mip_sizes: list[int] = []
        chunks: list[bytes] = []
        packed_off = 0
        for mip, source_off in enumerate(source_offsets):
            mip_w = max(1, width >> mip)
            mip_h = max(1, height >> mip)
            size = mip_data_size(mip_w, mip_h, fmt)
            src = data_base + source_off
            if src < 0 or src + size > len(physical_data):
                raise ValueError(
                    f"Texture data for '{name}' mip {mip} is outside the physical buffer "
                    f"(offset={src}, size={size}, buffer={len(physical_data)})"
                )
            packed_offsets.append(packed_off)
            mip_sizes.append(size)
            if include_data:
                mip_data = physical_data[src:src + size]
                chunks.append(_normalize_gcm_mip(
                    mip_data, mip_w, mip_h, fmt, format_byte,
                ))
            packed_off += size

        entry = {
            "name": name,
            "width": width,
            "height": height,
            "format": fmt,
            "format_name": fmt.name,
            "mip_count": mip_levels,
            "data_size": packed_off,
            "mip_offsets": packed_offsets,
            "mip_sizes": mip_sizes,
            "gcm_format": format_val,
        }
        if include_data:
            entry["data"] = b"".join(chunks)
        entries.append(entry)

    return entries


def _parse_gtav_ps3(file_data: bytes) -> ITD:
    td = ITD(game=Game.GTA5_PS3)
    for entry in _parse_gtav_ps3_entries(file_data, include_data=True):
        td.add(Texture.from_raw(
            entry["data"], entry["width"], entry["height"], entry["format"],
            entry["mip_count"], entry["mip_offsets"], entry["mip_sizes"],
            entry["name"],
        ))
    return td


def _inspect_gtav_ps3(file_data: bytes) -> list[dict]:
    result = []
    for entry in _parse_gtav_ps3_entries(file_data, include_data=False):
        result.append({
            "name": entry["name"],
            "width": entry["width"],
            "height": entry["height"],
            "format": entry["format"],
            "format_name": entry["format_name"],
            "mip_count": entry["mip_count"],
            "data_size": entry["data_size"],
            "gcm_format": entry["gcm_format"],
        })
    return result
