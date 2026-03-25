"""RAGE resource format (RSC8) encoding and assembly for RDR2 .ytd files."""

from __future__ import annotations

import struct
import zlib

DAT_VIRTUAL_BASE: int = 0x50000000
DAT_PHYSICAL_BASE: int = 0x60000000

RSC8_MAGIC: int = 0x38435352  # "RSC8" LE
RSC8_VERSION_YTD: int = 2


def _align(offset: int, alignment: int) -> int:
    return (offset + alignment - 1) & ~(alignment - 1)


def _deflate_compress(data: bytes, level: int = 9) -> bytes:
    co = zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS)
    return co.compress(data) + co.flush()


def _deflate_decompress(data: bytes, expected_size: int = 0) -> bytes:
    try:
        return zlib.decompress(data, -zlib.MAX_WBITS, expected_size or 0)
    except zlib.error:
        pass
    try:
        return zlib.decompress(data, zlib.MAX_WBITS)
    except zlib.error:
        pass
    return zlib.decompress(data, zlib.MAX_WBITS | 32)


def build_rsc8(virtual_data: bytes, physical_data: bytes,
               version: int = RSC8_VERSION_YTD) -> bytes:
    """Compress and wrap virtual + physical data into an RSC8 resource."""
    v_size = len(virtual_data)
    p_size = len(physical_data)

    v_aligned = _align(v_size, 0x10000 if v_size > 0x8000 else 16)
    p_aligned = _align(p_size, 0x10000 if p_size > 0x8000 else 16)

    v_flags = (v_aligned & 0xFFFFFFF0) | ((version >> 4) & 0xF)
    p_flags = (p_aligned & 0xFFFFFFF0) | (version & 0xF)

    padded = virtual_data.ljust(v_aligned, b"\x00")
    padded += physical_data.ljust(p_aligned, b"\x00")
    compressed = _deflate_compress(padded)

    header = struct.pack("<IIII", RSC8_MAGIC, version & 0xFF, v_flags, p_flags)
    return header + compressed


def decompress_rsc8(data: bytes) -> tuple[bytes, bytes]:
    """Decompress an RSC8 resource into (virtual_data, physical_data)."""
    if len(data) < 16:
        raise ValueError("Data too short for RSC8 header")
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != RSC8_MAGIC:
        raise ValueError(f"Bad RSC8 magic: 0x{magic:08X}")

    v_flags = struct.unpack_from("<I", data, 8)[0]
    p_flags = struct.unpack_from("<I", data, 12)[0]

    v_size = v_flags & 0xFFFFFFF0
    p_size = p_flags & 0xFFFFFFF0

    raw = _deflate_decompress(data[16:], v_size + p_size)
    return raw[:v_size], raw[v_size:v_size + p_size]
