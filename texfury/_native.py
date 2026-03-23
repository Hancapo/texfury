"""Low-level ctypes bindings to texfury_native.dll."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
from pathlib import Path

# ── Locate and load the DLL ──────────────────────────────────────────────────

_dll_dir = Path(__file__).parent
_dll_path = _dll_dir / "texfury_native.dll"

if not _dll_path.exists():
    raise FileNotFoundError(
        f"texfury_native.dll not found at {_dll_path}. "
        "Run native/build.bat to compile it."
    )

_lib = ctypes.CDLL(str(_dll_path))

# ── Type aliases ─────────────────────────────────────────────────────────────

c_uint8_p = ctypes.POINTER(ctypes.c_uint8)
c_size_t_p = ctypes.POINTER(ctypes.c_size_t)
c_uint8_pp = ctypes.POINTER(c_uint8_p)


class TfImage(ctypes.c_void_p):
    """Opaque handle to a native image."""
    pass


class TfCompressed(ctypes.c_void_p):
    """Opaque handle to compressed texture data."""
    pass


# ── Function signatures ─────────────────────────────────────────────────────

# Image lifecycle
_lib.tf_load_image.argtypes = [ctypes.c_wchar_p]
_lib.tf_load_image.restype = TfImage

_lib.tf_load_image_memory.argtypes = [c_uint8_p, ctypes.c_size_t]
_lib.tf_load_image_memory.restype = TfImage

_lib.tf_create_image.argtypes = [ctypes.c_int, ctypes.c_int, c_uint8_p]
_lib.tf_create_image.restype = TfImage

_lib.tf_free_image.argtypes = [TfImage]
_lib.tf_free_image.restype = None

# Image queries
_lib.tf_image_width.argtypes = [TfImage]
_lib.tf_image_width.restype = ctypes.c_int

_lib.tf_image_height.argtypes = [TfImage]
_lib.tf_image_height.restype = ctypes.c_int

_lib.tf_image_channels.argtypes = [TfImage]
_lib.tf_image_channels.restype = ctypes.c_int

_lib.tf_image_pixels.argtypes = [TfImage]
_lib.tf_image_pixels.restype = c_uint8_p

_lib.tf_has_transparency.argtypes = [TfImage]
_lib.tf_has_transparency.restype = ctypes.c_int

_lib.tf_is_power_of_two.argtypes = [ctypes.c_int, ctypes.c_int]
_lib.tf_is_power_of_two.restype = ctypes.c_int

_lib.tf_next_power_of_two.argtypes = [ctypes.c_int]
_lib.tf_next_power_of_two.restype = ctypes.c_int

# Image transforms
_lib.tf_resize.argtypes = [TfImage, ctypes.c_int, ctypes.c_int]
_lib.tf_resize.restype = TfImage

_lib.tf_resize_to_pot.argtypes = [TfImage]
_lib.tf_resize_to_pot.restype = TfImage

# Compression
_lib.tf_compress.argtypes = [
    TfImage,           # img
    ctypes.c_int,      # format (BCFormat)
    ctypes.c_int,      # generate_mipmaps
    ctypes.c_int,      # min_mip_dim
    ctypes.c_float,    # quality (0.0 - 1.0)
]
_lib.tf_compress.restype = TfCompressed

_lib.tf_free_compressed.argtypes = [TfCompressed]
_lib.tf_free_compressed.restype = None

# Compressed data accessors
_lib.tf_compressed_data.argtypes = [TfCompressed]
_lib.tf_compressed_data.restype = c_uint8_p

_lib.tf_compressed_size.argtypes = [TfCompressed]
_lib.tf_compressed_size.restype = ctypes.c_size_t

_lib.tf_compressed_width.argtypes = [TfCompressed]
_lib.tf_compressed_width.restype = ctypes.c_int

_lib.tf_compressed_height.argtypes = [TfCompressed]
_lib.tf_compressed_height.restype = ctypes.c_int

_lib.tf_compressed_format.argtypes = [TfCompressed]
_lib.tf_compressed_format.restype = ctypes.c_int

_lib.tf_compressed_mip_count.argtypes = [TfCompressed]
_lib.tf_compressed_mip_count.restype = ctypes.c_int

_lib.tf_compressed_mip_offset.argtypes = [TfCompressed, ctypes.c_int]
_lib.tf_compressed_mip_offset.restype = ctypes.c_size_t

_lib.tf_compressed_mip_size.argtypes = [TfCompressed, ctypes.c_int]
_lib.tf_compressed_mip_size.restype = ctypes.c_size_t

# DDS I/O
_lib.tf_save_dds.argtypes = [TfCompressed, ctypes.c_wchar_p]
_lib.tf_save_dds.restype = ctypes.c_int32

_lib.tf_save_dds_memory.argtypes = [TfCompressed, c_uint8_pp, c_size_t_p]
_lib.tf_save_dds_memory.restype = ctypes.c_int32

_lib.tf_load_dds.argtypes = [ctypes.c_wchar_p]
_lib.tf_load_dds.restype = TfCompressed

# Cleanup
_lib.tf_free_buffer.argtypes = [ctypes.c_void_p]
_lib.tf_free_buffer.restype = None


# ── Python-friendly wrappers ─────────────────────────────────────────────────

def load_image(path: str) -> TfImage:
    h = _lib.tf_load_image(path)
    if not h:
        raise FileNotFoundError(f"Failed to load image: {path}")
    return h

def load_image_memory(data: bytes) -> TfImage:
    buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    h = _lib.tf_load_image_memory(buf, len(data))
    if not h:
        raise ValueError("Failed to decode image from memory")
    return h

def create_image(width: int, height: int, rgba_data: bytes) -> TfImage:
    buf = (ctypes.c_uint8 * len(rgba_data)).from_buffer_copy(rgba_data)
    h = _lib.tf_create_image(width, height, buf)
    if not h:
        raise MemoryError("Failed to create image")
    return h

def free_image(h: TfImage) -> None:
    _lib.tf_free_image(h)

def image_width(h: TfImage) -> int:
    return _lib.tf_image_width(h)

def image_height(h: TfImage) -> int:
    return _lib.tf_image_height(h)

def image_channels(h: TfImage) -> int:
    return _lib.tf_image_channels(h)

def image_pixels(h: TfImage, width: int, height: int) -> bytes:
    ptr = _lib.tf_image_pixels(h)
    return ctypes.string_at(ptr, width * height * 4)

def has_transparency(h: TfImage) -> bool:
    return bool(_lib.tf_has_transparency(h))

def is_power_of_two(w: int, h: int) -> bool:
    return bool(_lib.tf_is_power_of_two(w, h))

def next_power_of_two(v: int) -> int:
    return _lib.tf_next_power_of_two(v)

def resize(h: TfImage, w: int, hh: int) -> TfImage:
    r = _lib.tf_resize(h, w, hh)
    if not r:
        raise RuntimeError("Failed to resize image")
    return r

def resize_to_pot(h: TfImage) -> TfImage:
    r = _lib.tf_resize_to_pot(h)
    if not r:
        raise RuntimeError("Failed to resize to power-of-two")
    return r

def compress(h: TfImage, fmt: int, mipmaps: bool, min_mip: int,
             quality: float) -> TfCompressed:
    c = _lib.tf_compress(h, fmt, 1 if mipmaps else 0, min_mip, quality)
    if not c:
        raise RuntimeError("Compression failed")
    return c

def free_compressed(c: TfCompressed) -> None:
    _lib.tf_free_compressed(c)

def compressed_data(c: TfCompressed) -> bytes:
    ptr = _lib.tf_compressed_data(c)
    sz = _lib.tf_compressed_size(c)
    return ctypes.string_at(ptr, sz)

def compressed_width(c: TfCompressed) -> int:
    return _lib.tf_compressed_width(c)

def compressed_height(c: TfCompressed) -> int:
    return _lib.tf_compressed_height(c)

def compressed_format(c: TfCompressed) -> int:
    return _lib.tf_compressed_format(c)

def compressed_mip_count(c: TfCompressed) -> int:
    return _lib.tf_compressed_mip_count(c)

def compressed_mip_offset(c: TfCompressed, mip: int) -> int:
    return _lib.tf_compressed_mip_offset(c, mip)

def compressed_mip_size(c: TfCompressed, mip: int) -> int:
    return _lib.tf_compressed_mip_size(c, mip)

def save_dds(c: TfCompressed, path: str) -> None:
    rc = _lib.tf_save_dds(c, path)
    if rc != 0:
        raise IOError(f"Failed to save DDS file: {path} (error {rc})")

def save_dds_memory(c: TfCompressed) -> bytes:
    buf_ptr = c_uint8_p()
    size = ctypes.c_size_t(0)
    rc = _lib.tf_save_dds_memory(c, ctypes.byref(buf_ptr), ctypes.byref(size))
    if rc != 0:
        raise RuntimeError(f"Failed to save DDS to memory (error {rc})")
    data = ctypes.string_at(buf_ptr, size.value)
    _lib.tf_free_buffer(buf_ptr)
    return data

def load_dds(path: str) -> TfCompressed:
    c = _lib.tf_load_dds(path)
    if not c:
        raise FileNotFoundError(f"Failed to load DDS: {path}")
    return c
