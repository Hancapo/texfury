"""RAGE resource format (RSC7) encoding and assembly for GTA V .ytd files."""

from __future__ import annotations

import struct
import zlib

DAT_VIRTUAL_BASE: int = 0x50000000
DAT_PHYSICAL_BASE: int = 0x60000000
DAT_BASE_SIZE: int = 0x2000

RSC7_MAGIC: int = 0x37435352
RSC7_VERSION_YTD: int = 13


def _size_shift(data: int) -> int:
    return (data & 0xF) + 4


def decode_chunk_sizes(data: int) -> list[int]:
    if data == 0:
        return []

    shift = _size_shift(data)
    base = DAT_BASE_SIZE << shift

    counts = [
        (data >> 4) & 0x1, (data >> 5) & 0x3, (data >> 7) & 0xF,
        (data >> 11) & 0x3F, (data >> 17) & 0x7F, (data >> 24) & 0x1,
        (data >> 25) & 0x1, (data >> 26) & 0x1, (data >> 27) & 0x1,
    ]

    sizes: list[int] = []
    current_size = base
    for c in counts:
        for _ in range(c):
            sizes.append(current_size)
        current_size >>= 1
    return sizes


def total_from_flags(data: int) -> int:
    return sum(decode_chunk_sizes(data))


def encode_flags(needed_size: int) -> int:
    if needed_size <= 0:
        return 0
    for shift_val in range(16):
        chunk_size = DAT_BASE_SIZE << (shift_val + 4)
        if chunk_size >= needed_size:
            return shift_val | (1 << 4)
    raise ValueError(f"Size {needed_size} exceeds maximum single chunk")


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


def build_rsc7(virtual_data: bytes, physical_data: bytes,
               version: int = RSC7_VERSION_YTD) -> bytes:
    sys_flags = encode_flags(len(virtual_data))
    gfx_flags = encode_flags(len(physical_data)) if physical_data else 0

    sys_chunk_size = total_from_flags(sys_flags)
    gfx_chunk_size = total_from_flags(gfx_flags) if gfx_flags else 0

    padded_virtual = virtual_data.ljust(sys_chunk_size, b"\x00")
    padded_physical = physical_data.ljust(gfx_chunk_size, b"\x00") if gfx_flags else b""

    compressed = _deflate_compress(padded_virtual + padded_physical)
    header = struct.pack("<IIII", RSC7_MAGIC, version, sys_flags, gfx_flags)
    return header + compressed


def parse_rsc7_header(data: bytes) -> tuple[int, int, int]:
    if len(data) < 16:
        raise ValueError("Data too short for RSC7 header")
    magic, version, sys_flags, gfx_flags = struct.unpack_from("<IIII", data)
    if magic != RSC7_MAGIC:
        raise ValueError(f"Bad RSC7 magic: 0x{magic:08X}")
    return version, sys_flags, gfx_flags


def decompress_rsc7(data: bytes) -> tuple[bytes, bytes]:
    _, sys_flags, gfx_flags = parse_rsc7_header(data)
    compressed = data[16:]
    sys_size = total_from_flags(sys_flags)
    gfx_size = total_from_flags(gfx_flags)
    raw = _deflate_decompress(compressed, sys_size + gfx_size)
    return raw[:sys_size], raw[sys_size:sys_size + gfx_size]
