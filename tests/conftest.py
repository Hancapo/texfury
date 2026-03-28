"""Shared fixtures for texfury tests."""

import struct
import zlib
from pathlib import Path

import pytest


def _make_png(w: int, h: int, r: int = 128, g: int = 128, b: int = 255, a: int = 255) -> bytes:
    """Create a minimal valid RGBA PNG in memory."""
    raw = b""
    for _ in range(h):
        raw += b"\x00" + bytes([r, g, b, a]) * w
    compressed = zlib.compress(raw)

    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        crc = zlib.crc32(c) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + c + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def png_64(tmp_path: Path) -> Path:
    """64x64 opaque PNG."""
    p = tmp_path / "test_64.png"
    p.write_bytes(_make_png(64, 64, 255, 0, 0))
    return p


@pytest.fixture
def png_128(tmp_path: Path) -> Path:
    """128x128 opaque PNG."""
    p = tmp_path / "test_128.png"
    p.write_bytes(_make_png(128, 128, 0, 255, 0))
    return p


@pytest.fixture
def png_256(tmp_path: Path) -> Path:
    """256x256 opaque PNG."""
    p = tmp_path / "test_256.png"
    p.write_bytes(_make_png(256, 256, 0, 0, 255))
    return p


@pytest.fixture
def png_transparent(tmp_path: Path) -> Path:
    """64x64 PNG with transparency."""
    p = tmp_path / "test_transparent.png"
    p.write_bytes(_make_png(64, 64, 255, 0, 0, 128))
    return p


@pytest.fixture
def image_folder(tmp_path: Path) -> Path:
    """Folder with 3 test PNGs."""
    folder = tmp_path / "images"
    folder.mkdir()
    (folder / "red.png").write_bytes(_make_png(64, 64, 255, 0, 0))
    (folder / "green.png").write_bytes(_make_png(128, 128, 0, 255, 0))
    (folder / "blue.png").write_bytes(_make_png(256, 256, 0, 0, 255))
    return folder


@pytest.fixture
def vanilla_wtd() -> Path | None:
    """Path to the vanilla GTA IV WTD for integration tests.

    Returns None if the file is not present (CI environments).
    """
    p = Path(__file__).resolve().parent.parent / "nj04e_glue.wtd"
    return p if p.exists() else None
