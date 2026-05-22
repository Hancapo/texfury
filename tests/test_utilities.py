"""Test image utility functions."""

import struct
import zlib

import pytest

from texfury import (
    has_transparency, is_power_of_two, next_power_of_two,
    pot_dimensions, fit_dimensions, image_dimensions,
    resize_image, resize_image_to_max, Texture, BCFormat,
)
from texfury import _native as native


def _make_png(w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + bytes([255, 0, 0, 255]) * w for _ in range(h))

    def chunk(ctype: bytes, data: bytes) -> bytes:
        payload = ctype + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class TestPowerOfTwo:
    def test_both_pot(self):
        assert is_power_of_two(256, 512) is True

    def test_not_pot(self):
        assert is_power_of_two(300, 400) is False

    def test_one_pot_one_not(self):
        assert is_power_of_two(256, 300) is False

    def test_1x1(self):
        assert is_power_of_two(1, 1) is True


class TestNextPowerOfTwo:
    def test_exact(self):
        assert next_power_of_two(256) == 256

    def test_round_up(self):
        assert next_power_of_two(100) == 128

    def test_large(self):
        assert next_power_of_two(500) == 512

    def test_one(self):
        assert next_power_of_two(1) == 1


class TestPotDimensions:
    def test_basic(self):
        assert pot_dimensions(300, 400) == (256, 512)

    def test_large(self):
        assert pot_dimensions(1920, 1080) == (2048, 1024)

    def test_already_pot(self):
        assert pot_dimensions(256, 256) == (256, 256)

    def test_just_above_pot(self):
        assert pot_dimensions(1025, 513) == (1024, 512)


class TestFitDimensions:
    def test_fits_inside_max_size(self):
        assert fit_dimensions(512, 1024, 512) == (256, 512)

    def test_does_not_upscale_by_default(self):
        assert fit_dimensions(300, 400, 512) == (300, 400)

    def test_can_upscale(self):
        assert fit_dimensions(300, 400, 512, allow_upscale=True) == (384, 512)

    def test_rejects_invalid_dimensions(self):
        with pytest.raises(ValueError):
            fit_dimensions(0, 100, 512)
        with pytest.raises(ValueError):
            fit_dimensions(100, 100, 0)


class TestResizeToPot:
    def test_just_above_pot_resizes_down(self):
        img = native.create_image(1025, 513, bytes(1025 * 513 * 4))
        try:
            resized = native.resize_to_pot(img)
            try:
                assert native.image_width(resized) == 1024
                assert native.image_height(resized) == 512
            finally:
                native.free_image(resized)
        finally:
            native.free_image(img)


class TestNativeValidation:
    def test_create_image_rejects_short_rgba_buffer(self):
        with pytest.raises(ValueError):
            native.create_image(2, 2, bytes(15))

    def test_metrics_reject_short_rgba_buffers(self):
        with pytest.raises(ValueError):
            native.psnr(bytes(15), bytes(16), 2, 2)
        with pytest.raises(ValueError):
            native.ssim(bytes(16), bytes(15), 2, 2)


class TestImageDimensions:
    def test_png(self, png_64):
        w, h, ch = image_dimensions(str(png_64))
        assert w == 64
        assert h == 64
        assert ch == 4

    def test_png_128(self, png_128):
        w, h, ch = image_dimensions(str(png_128))
        assert w == 128
        assert h == 128


class TestResizeImage:
    def test_resize_image_returns_raw_rgba(self, png_128):
        rgba, w, h = resize_image(str(png_128), 32, 64)
        assert (w, h) == (32, 64)
        assert len(rgba) == 32 * 64 * 4

    def test_resize_image_to_max_preserves_aspect(self, tmp_path):
        path = tmp_path / "rect.png"
        path.write_bytes(_make_png(100, 200))

        rgba, w, h = resize_image_to_max(str(path), 90)
        assert (w, h) == (45, 90)
        assert len(rgba) == 45 * 90 * 4


class TestPreCompressionResize:
    def test_from_image_can_resize_before_compression(self, tmp_path):
        path = tmp_path / "rect.png"
        path.write_bytes(_make_png(100, 200))

        tex = Texture.from_image(
            str(path),
            format=BCFormat.BC1,
            max_size=90,
            generate_mipmaps=False,
        )
        assert (tex.width, tex.height) == (45, 90)

    def test_resize_and_max_size_are_mutually_exclusive(self, png_128):
        with pytest.raises(ValueError):
            Texture.from_image(
                str(png_128),
                resize=(64, 64),
                max_size=64,
                generate_mipmaps=False,
            )


class TestHasTransparency:
    def test_opaque(self, png_64):
        assert has_transparency(str(png_64)) is False

    def test_transparent(self, png_transparent):
        assert has_transparency(str(png_transparent)) is True
