"""RAGE resource format (RSC5) — GTA IV .wtd files."""

from __future__ import annotations

import struct
import zlib

RSC5_MAGIC: int = 0x05435352  # "RSC5" LE
RSC5_RESOURCE_TYPE_TEXTURE: int = 0x8


def _get_count_shift(size: int) -> tuple[int, int]:
    """Find count and shift so that count << (shift + 8) >= size."""
    if size <= 0:
        return 0, 0
    shift = 0
    while True:
        block_size = 1 << (shift + 8)
        count = (size + block_size - 1) // block_size
        if count <= 0x7FF:
            break
        shift += 1
        if shift > 0xF:
            count = 0x7FF
            break
    return count, shift


def build_rsc5_flags(virtual_size: int, physical_size: int,
                     version: int = 3) -> int:
    """Encode virtual/physical sizes + version into a single RSC5 flags uint32."""
    vc, vs = _get_count_shift(virtual_size)
    pc, ps = _get_count_shift(physical_size)
    flags = (version & 0x3) << 30
    flags |= vc & 0x7FF
    flags |= (vs & 0xF) << 11
    flags |= (pc & 0x7FF) << 15
    flags |= (ps & 0xF) << 26
    return flags


def decode_rsc5_flags(flags: int) -> tuple[int, int, int]:
    """Decode RSC5 flags into (version, virtual_size, physical_size)."""
    version = (flags >> 30) & 0x3
    vc = flags & 0x7FF
    vs = (flags >> 11) & 0xF
    pc = (flags >> 15) & 0x7FF
    ps = (flags >> 26) & 0xF
    v_size = vc << (vs + 8)
    p_size = pc << (ps + 8)
    return version, v_size, p_size


def build_rsc5(virtual_data: bytes, physical_data: bytes,
               version: int = 3) -> bytes:
    """Compress and wrap virtual + physical data into an RSC5 resource."""
    v_size = len(virtual_data)
    p_size = len(physical_data)

    flags = build_rsc5_flags(v_size, p_size, version)
    _, v_alloc, p_alloc = decode_rsc5_flags(flags)

    padded = virtual_data.ljust(v_alloc, b"\x00")
    padded += physical_data.ljust(p_alloc, b"\x00")

    compressed = zlib.compress(padded, 9)

    header = struct.pack("<III", RSC5_MAGIC, RSC5_RESOURCE_TYPE_TEXTURE, flags)
    return header + compressed


def decompress_rsc5(data: bytes) -> tuple[bytes, bytes]:
    """Decompress an RSC5 resource into (virtual_data, physical_data)."""
    if len(data) < 12:
        raise ValueError("Data too short for RSC5 header")
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != RSC5_MAGIC:
        raise ValueError(f"Bad RSC5 magic: 0x{magic:08X}")

    flags = struct.unpack_from("<I", data, 8)[0]
    _, v_size, p_size = decode_rsc5_flags(flags)

    raw = zlib.decompress(data[12:])
    return raw[:v_size], raw[v_size:v_size + p_size]
