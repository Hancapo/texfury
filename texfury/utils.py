"""Standalone image utility functions."""

from __future__ import annotations

from pathlib import Path

from texfury import _native as native
from texfury.formats import MipFilter

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
    return (native.nearest_power_of_two(width),
            native.nearest_power_of_two(height))


def fit_dimensions(width: int, height: int, max_size: int, *,
                   allow_upscale: bool = False) -> tuple[int, int]:
    """Return dimensions that fit inside max_size while preserving aspect ratio."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if max_size <= 0:
        raise ValueError("max_size must be positive")

    scale = min(max_size / width, max_size / height)
    if not allow_upscale:
        scale = min(scale, 1.0)
    return (max(1, round(width * scale)),
            max(1, round(height * scale)))


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


def resize_image(source: str | Path, width: int, height: int, *,
                 filter: MipFilter = MipFilter.MITCHELL) -> tuple[bytes, int, int]:
    """Load an image, resize it, and return raw RGBA bytes without compression."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    img = native.load_image(str(Path(source).resolve()))
    try:
        resized = native.resize(img, width, height, int(filter))
        try:
            rgba = native.image_pixels(resized, width, height)
            return rgba, width, height
        finally:
            native.free_image(resized)
    finally:
        native.free_image(img)


def resize_image_to_max(source: str | Path, max_size: int, *,
                        filter: MipFilter = MipFilter.MITCHELL,
                        allow_upscale: bool = False) -> tuple[bytes, int, int]:
    """Resize an image to fit inside max_size and return raw RGBA bytes."""
    width, height, _ = image_dimensions(source)
    new_w, new_h = fit_dimensions(
        width, height, max_size, allow_upscale=allow_upscale)
    return resize_image(source, new_w, new_h, filter=filter)
