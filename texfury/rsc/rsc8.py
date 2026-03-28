"""RAGE resource format (RSC8) — RDR2 .ytd files."""

from __future__ import annotations

import ctypes
import struct
import zlib
from pathlib import Path

from texfury.formats import RscCompression

RSC8_MAGIC: int = 0x38435352  # "RSC8" LE
RSC8_VERSION_YTD: int = 2


def _align(offset: int, alignment: int) -> int:
    return (offset + alignment - 1) & ~(alignment - 1)


# ── Deflate (zlib) ──────────────────────────────────────────────────────────

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


# ── Oodle ───────────────────────────────────────────────────────────────────

_oodle_dll: ctypes.CDLL | None = None

_OODLE_DLL_NAMES = [
    "oo2core_5_win64",
    "oo2core_9_win64",
    "oo2core_8_win64",
    "oo2core_7_win64",
    "oo2core_6_win64",
]


def _find_oodle() -> ctypes.CDLL:
    """Locate and load the Oodle DLL."""
    global _oodle_dll
    if _oodle_dll is not None:
        return _oodle_dll

    # Try DLL names in PATH / system
    for name in _OODLE_DLL_NAMES:
        try:
            _oodle_dll = ctypes.CDLL(name)
            return _oodle_dll
        except OSError:
            pass

    # Try bundled DLL next to this file
    dll_dir = Path(__file__).resolve().parent.parent
    for name in _OODLE_DLL_NAMES:
        p = dll_dir / f"{name}.dll"
        if p.exists():
            _oodle_dll = ctypes.CDLL(str(p))
            return _oodle_dll

    raise RuntimeError(
        "Oodle decompression library not found. "
        "Place oo2core_5_win64.dll (or similar) next to the texfury package "
        "or in a directory on your PATH."
    )


def _oodle_decompress(data: bytes, decompressed_size: int) -> bytes:
    """Decompress data using Oodle (Kraken)."""
    dll = _find_oodle()
    func = dll.OodleLZ_Decompress

    src = ctypes.create_string_buffer(data, len(data))
    dst = ctypes.create_string_buffer(decompressed_size)

    result = func(
        src, ctypes.c_longlong(len(data)),
        dst, ctypes.c_longlong(decompressed_size),
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    )

    if result != decompressed_size:
        raise RuntimeError(
            f"Oodle decompression failed: expected {decompressed_size} bytes, "
            f"got {result}"
        )
    return dst.raw


# Oodle compression constants
_OODLE_FORMAT_KRAKEN: int = 8
_OODLE_LEVEL_NORMAL: int = 4


def _oodle_compressed_bounds(size: int) -> int:
    """Maximum output buffer size for Oodle compression."""
    return size + (size // 4) + 0x10000


def _oodle_compress(data: bytes) -> bytes:
    """Compress data using Oodle Kraken."""
    dll = _find_oodle()
    func = dll.OodleLZ_Compress
    func.restype = ctypes.c_longlong
    func.argtypes = [
        ctypes.c_int,                              # format
        ctypes.POINTER(ctypes.c_char),             # source
        ctypes.c_longlong,                         # source size
        ctypes.POINTER(ctypes.c_char),             # dest
        ctypes.c_int,                              # level
        ctypes.c_longlong,                         # unused
        ctypes.c_longlong,                         # unused
        ctypes.c_longlong,                         # unused
    ]

    src_len = len(data)
    max_size = _oodle_compressed_bounds(src_len)

    src_buf = (ctypes.c_char * src_len).from_buffer_copy(data)
    dst_buf = (ctypes.c_char * max_size)()

    compressed_size = func(
        _OODLE_FORMAT_KRAKEN,
        src_buf, ctypes.c_longlong(src_len),
        dst_buf, _OODLE_LEVEL_NORMAL,
        0, 0, 0,
    )

    if compressed_size <= 0:
        raise RuntimeError("Oodle compression failed")
    return bytes(dst_buf[:compressed_size])


# ── RSC8 header helpers ─────────────────────────────────────────────────────

def _parse_compressor_id(version_field: int) -> int:
    """Extract the compressor ID from the RSC8 version field."""
    return ((version_field >> 8) & 0x1F) + 1


def _encode_version(version: int, compressor_id: int = RscCompression.DEFLATE) -> int:
    """Encode version + compressor ID into the RSC8 version field."""
    return (version & 0xFF) | (((compressor_id - 1) & 0x1F) << 8)


# ── Public API ──────────────────────────────────────────────────────────────

def build_rsc8(virtual_data: bytes, physical_data: bytes,
               version: int = RSC8_VERSION_YTD, *,
               compression: RscCompression = RscCompression.OODLE) -> bytes:
    """Compress and wrap virtual + physical data into an RSC8 resource.

    Uses Oodle Kraken compression by default (matching RDR2 vanilla files).
    Falls back to deflate if Oodle DLL is not available.
    """
    v_size = len(virtual_data)
    p_size = len(physical_data)

    v_aligned = _align(v_size, 0x10000 if v_size > 0x8000 else 16)
    p_aligned = _align(p_size, 0x10000 if p_size > 0x8000 else 16)

    v_flags = (v_aligned & 0xFFFFFFF0) | ((version >> 4) & 0xF)
    p_flags = (p_aligned & 0xFFFFFFF0) | (version & 0xF)

    padded = virtual_data.ljust(v_aligned, b"\x00")
    padded += physical_data.ljust(p_aligned, b"\x00")

    if compression == RscCompression.OODLE:
        try:
            compressed = _oodle_compress(padded)
            compressor_id = RscCompression.OODLE
        except (RuntimeError, OSError):
            compressed = _deflate_compress(padded)
            compressor_id = RscCompression.DEFLATE
    else:
        compressed = _deflate_compress(padded)
        compressor_id = RscCompression.DEFLATE

    version_field = _encode_version(version, compressor_id)
    header = struct.pack("<IIII", RSC8_MAGIC, version_field, v_flags, p_flags)
    return header + compressed


def decompress_rsc8(data: bytes) -> tuple[bytes, bytes]:
    """Decompress an RSC8 resource into (virtual_data, physical_data).

    Supports both deflate (zlib) and Oodle compression.
    """
    if len(data) < 16:
        raise ValueError("Data too short for RSC8 header")
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != RSC8_MAGIC:
        raise ValueError(f"Bad RSC8 magic: 0x{magic:08X}")

    version_field = struct.unpack_from("<I", data, 4)[0]
    v_flags = struct.unpack_from("<I", data, 8)[0]
    p_flags = struct.unpack_from("<I", data, 12)[0]

    v_size = v_flags & 0xFFFFFFF0
    p_size = p_flags & 0xFFFFFFF0
    total_size = v_size + p_size

    compressor = _parse_compressor_id(version_field)
    payload = data[16:]

    if compressor == RscCompression.OODLE:
        raw = _oodle_decompress(payload, total_size)
    else:
        raw = _deflate_decompress(payload, total_size)

    return raw[:v_size], raw[v_size:v_size + p_size]
