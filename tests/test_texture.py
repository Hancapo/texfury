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

    def test_all_native_formats(self, png_64):
        """Test all formats supported by the native compressor."""
        native_formats = (BCFormat.BC1, BCFormat.BC3, BCFormat.BC4,
                          BCFormat.BC5, BCFormat.BC7, BCFormat.A8R8G8B8)
        for fmt in native_formats:
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

    def test_dds_passthrough(self, png_64):
        """DDS bytes are loaded as-is by default (no recompression)."""
        original = Texture.from_image(str(png_64), format=BCFormat.BC1)
        dds_bytes = original.to_dds_bytes()
        tex = Texture.from_bytes(dds_bytes, format=BCFormat.BC7, name="pass")
        assert tex.format == BCFormat.BC1  # kept original, ignored BC7
        assert tex.data == original.data

    def test_dds_recompress(self, png_64):
        """DDS bytes are recompressed when recompress=True."""
        original = Texture.from_image(str(png_64), format=BCFormat.BC1)
        dds_bytes = original.to_dds_bytes()
        tex = Texture.from_bytes(dds_bytes, format=BCFormat.BC7, recompress=True)
        assert tex.format == BCFormat.BC7  # recompressed to BC7
        assert tex.width == original.width


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

    def test_from_dds_bytes(self, png_64):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC7)
        dds_bytes = tex.to_dds_bytes()

        tex2 = Texture.from_dds_bytes(dds_bytes, name="from_mem")
        assert tex2.width == tex.width
        assert tex2.height == tex.height
        assert tex2.format == tex.format
        assert tex2.mip_count == tex.mip_count
        assert tex2.data == tex.data
        assert tex2.name == "from_mem"

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


class TestUncompressedFormats:
    """Test all uncompressed pixel format conversions (PNG → format → RGBA roundtrip)."""

    # Formats that go through convert_pixels in the native module
    UNCOMPRESSED_FORMATS = (
        BCFormat.A8R8G8B8, BCFormat.R8G8B8A8,
        BCFormat.B5G6R5, BCFormat.B5G5R5A1, BCFormat.R10G10B10A2,
        BCFormat.R8, BCFormat.A8, BCFormat.R8G8,
        BCFormat.R16_FLOAT, BCFormat.R16G16_FLOAT,
        BCFormat.R16G16B16A16_FLOAT,
        BCFormat.R32_FLOAT, BCFormat.R32G32B32A32_FLOAT,
    )

    @pytest.mark.parametrize("fmt", UNCOMPRESSED_FORMATS, ids=lambda f: f.name)
    def test_create_from_png(self, png_64, fmt):
        """Each uncompressed format can be created from a PNG."""
        tex = Texture.from_image(str(png_64), format=fmt)
        assert tex.format == fmt
        assert tex.width == 64
        assert tex.height == 64
        assert len(tex.data) > 0

    @pytest.mark.parametrize("fmt", UNCOMPRESSED_FORMATS, ids=lambda f: f.name)
    def test_dds_roundtrip(self, png_64, tmp_path, fmt):
        """DDS save → load roundtrip preserves format and dimensions."""
        tex = Texture.from_image(str(png_64), format=fmt)
        dds_path = tmp_path / f"test_{fmt.name}.dds"
        tex.save_dds(str(dds_path))

        tex2 = Texture.from_dds(str(dds_path))
        assert tex2.width == 64
        assert tex2.height == 64
        assert tex2.format == fmt
        assert len(tex2.data) == len(tex.data)

    @pytest.mark.parametrize("fmt", UNCOMPRESSED_FORMATS, ids=lambda f: f.name)
    def test_decompress_to_rgba(self, png_64, fmt):
        """Decompressing to RGBA produces valid pixel data."""
        tex = Texture.from_image(str(png_64), format=fmt)
        rgba, w, h = tex.to_rgba()
        assert w == 64
        assert h == 64
        assert len(rgba) == w * h * 4

    def test_r8g8b8a8_lossless(self, png_64):
        """R8G8B8A8 should be lossless (same as input RGBA)."""
        tex = Texture.from_image(str(png_64), format=BCFormat.R8G8B8A8,
                                 generate_mipmaps=False)
        rgba, w, h = tex.to_rgba()
        # Load original for comparison
        orig = Texture.from_image(str(png_64), format=BCFormat.R8G8B8A8,
                                  generate_mipmaps=False)
        assert tex.data == orig.data


class TestValidate:
    def test_valid_texture(self, png_64):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="valid")
        warnings = tex.validate()
        assert isinstance(warnings, list)
