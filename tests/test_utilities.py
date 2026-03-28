"""Test image utility functions."""

from texfury import (
    has_transparency, is_power_of_two, next_power_of_two,
    pot_dimensions, image_dimensions,
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
        assert pot_dimensions(300, 400) == (512, 512)

    def test_large(self):
        assert pot_dimensions(1920, 1080) == (2048, 2048)

    def test_already_pot(self):
        assert pot_dimensions(256, 256) == (256, 256)


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


class TestHasTransparency:
    def test_opaque(self, png_64):
        assert has_transparency(str(png_64)) is False

    def test_transparent(self, png_transparent):
        assert has_transparency(str(png_transparent)) is True
