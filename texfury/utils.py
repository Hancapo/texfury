"""Standalone image utility functions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from texfury import _native as native

try:
    from PIL import Image as PILImage
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def has_transparency(source: str | Path) -> bool:
    """Check if an image file has any transparent pixels.

    Also accepts a PIL Image if Pillow is installed (pass via
    has_transparency_pil instead).
    """
    img = native.load_image(str(Path(source).resolve()))
    try:
        return native.has_transparency(img)
    finally:
        native.free_image(img)


def has_transparency_pil(image) -> bool:
    """Check if a PIL Image has any transparent pixels."""
    if not _HAS_PIL:
        raise ImportError("Pillow is required. Install with: pip install Pillow")
    if image.mode != "RGBA":
        return False
    extrema = image.getchannel("A").getextrema()
    return extrema[0] < 255


def is_power_of_two(width: int, height: int) -> bool:
    """Check if both dimensions are powers of two."""
    return native.is_power_of_two(width, height)


def next_power_of_two(value: int) -> int:
    """Return the next power of two >= value."""
    return native.next_power_of_two(value)


def pot_dimensions(width: int, height: int) -> tuple[int, int]:
    """Return the nearest power-of-two dimensions for the given size."""
    return (native.next_power_of_two(width),
            native.next_power_of_two(height))


def image_dimensions(source: str | Path) -> tuple[int, int, int]:
    """Get image dimensions and channel count without full decompression.

    Returns (width, height, channels).
    """
    img = native.load_image(str(Path(source).resolve()))
    try:
        return (native.image_width(img),
                native.image_height(img),
                native.image_channels(img))
    finally:
        native.free_image(img)
