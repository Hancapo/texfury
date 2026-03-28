"""Test Texture creation, serialization, and decompression."""

from pathlib import Path

import pytest

from texfury import Texture, BCFormat, MipFilter


class TestFromImage:
    def test_basic(self, png_64):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1)
        assert tex.width == 64
        assert tex.height == 64
        assert tex.format == BCFormat.BC1
        assert tex.mip_count >= 1
        assert len(tex.data) > 0

    def test_name_from_filename(self, png_64):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1)
        assert tex.name == "test_64"

    def test_custom_name(self, png_64):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="custom")
        assert tex.name == "custom"

    def test_all_bc_formats(self, png_64):
        for fmt in BCFormat:
            tex = Texture.from_image(str(png_64), format=fmt)
            assert tex.format == fmt
            assert tex.width == 64
            assert len(tex.data) > 0

    def test_quality_range(self, png_64):
        for q in (0.0, 0.5, 1.0):
            tex = Texture.from_image(str(png_64), format=BCFormat.BC7, quality=q)
            assert tex.width == 64

    def test_no_mipmaps(self, png_64):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, generate_mipmaps=False)
        assert tex.mip_count == 1

    def test_all_mip_filters(self, png_128):
        for filt in MipFilter:
            tex = Texture.from_image(str(png_128), format=BCFormat.BC1, mip_filter=filt)
            assert tex.mip_count >= 1


class TestFromBytes:
    def test_basic(self, png_64):
        data = png_64.read_bytes()
        tex = Texture.from_bytes(data, format=BCFormat.BC1, name="frombytes")
        assert tex.width == 64
        assert tex.height == 64
        assert tex.name == "frombytes"


class TestDdsRoundTrip:
    def test_save_and_load(self, png_64, tmp_path):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC7)
        dds_path = tmp_path / "test.dds"
        tex.save_dds(str(dds_path))

        tex2 = Texture.from_dds(str(dds_path))
        assert tex2.width == tex.width
        assert tex2.height == tex.height
        assert tex2.format == tex.format
        assert tex2.mip_count == tex.mip_count
        assert len(tex2.data) == len(tex.data)

    def test_to_dds_bytes(self, png_64, tmp_path):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1)
        dds_path = tmp_path / "test.dds"
        tex.save_dds(str(dds_path))

        dds_bytes = tex.to_dds_bytes()
        assert dds_bytes == dds_path.read_bytes()


class TestDecompression:
    def test_to_rgba(self, png_128):
        tex = Texture.from_image(str(png_128), format=BCFormat.BC1)
        rgba, w, h = tex.to_rgba()
        assert w == tex.width
        assert h == tex.height
        assert len(rgba) == w * h * 4

    def test_to_rgba_mip1(self, png_128):
        tex = Texture.from_image(str(png_128), format=BCFormat.BC1)
        if tex.mip_count > 1:
            rgba, w, h = tex.to_rgba(mip=1)
            assert w == max(1, tex.width // 2)
            assert h == max(1, tex.height // 2)
            assert len(rgba) == w * h * 4

    def test_all_native_formats_decompress(self, png_64):
        """Test decompression for all formats supported by the native compressor."""
        native_formats = (BCFormat.BC1, BCFormat.BC3, BCFormat.BC4,
                          BCFormat.BC5, BCFormat.BC7, BCFormat.A8R8G8B8)
        for fmt in native_formats:
            tex = Texture.from_image(str(png_64), format=fmt)
            rgba, w, h = tex.to_rgba()
            assert len(rgba) == w * h * 4


class TestInspectDds:
    def test_basic(self, png_64, tmp_path):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC7, name="inspected")
        dds_path = tmp_path / "inspect.dds"
        tex.save_dds(str(dds_path))

        info = Texture.inspect_dds(str(dds_path))
        assert info["width"] == 64
        assert info["height"] == 64
        assert info["format"] == BCFormat.BC7
        assert info["format_name"] == "BC7"
        assert info["mip_count"] == tex.mip_count
        assert "data_size" in info


class TestValidate:
    def test_valid_texture(self, png_64):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="valid")
        warnings = tex.validate()
        assert isinstance(warnings, list)
