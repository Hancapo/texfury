"""Low-level binary reading, alignment, and hashing helpers."""

from __future__ import annotations

import struct


# ── Byte readers (little-endian) ────────────────────────────────────────────

def r_u8(d: bytes, o: int) -> int: return d[o]
def r_u16(d: bytes, o: int) -> int: return struct.unpack_from("<H", d, o)[0]
def r_i16(d: bytes, o: int) -> int: return struct.unpack_from("<h", d, o)[0]
def r_u32(d: bytes, o: int) -> int: return struct.unpack_from("<I", d, o)[0]
def r_u64(d: bytes, o: int) -> int: return struct.unpack_from("<Q", d, o)[0]


# ── Alignment ───────────────────────────────────────────────────────────────

def align(offset: int, alignment: int) -> int:
    """Round *offset* up to nearest multiple of *alignment*."""
    return (offset + alignment - 1) & ~(alignment - 1)


# ── Hashing ─────────────────────────────────────────────────────────────────

def joaat(text: str) -> int:
    """Jenkins One-at-a-Time hash (lowercase)."""
    h = 0
    for c in text.lower():
        h = (h + ord(c)) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= (h >> 6)
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= (h >> 11)
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h
