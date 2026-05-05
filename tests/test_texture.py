"""Test Texture creation, serialization, and decompression."""

from pathlib import Path
import struct

import pytest

from texfury import Texture, BCFormat, MipFilter
from texfury.texture_dict import ITD, Game


def _png_rgba_bytes(width: int, height: int, pixels: bytes) -> bytes:
    import zlib

    raw = b"".join(
        b"\x00" + pixels[y * width * 4:(y + 1) * width * 4]
        for y in range(height)
    )

    def chunk(ctype: bytes, data: bytes) -> bytes:
        payload = ctype + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _dds_fourcc_bytes(width: int, height: int, fourcc: bytes,
                      pixel_data: bytes) -> bytes:
    hdr = bytearray(124)
    struct.pack_into("<I", hdr, 0, 124)
    struct.pack_into("<I", hdr, 4, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000)
    struct.pack_into("<I", hdr, 8, height)
    struct.pack_into("<I", hdr, 12, width)
    struct.pack_into("<I", hdr, 16, len(pixel_data))
    struct.pack_into("<I", hdr, 20, 1)
    struct.pack_into("<I", hdr, 24, 1)
    struct.pack_into("<I", hdr, 72, 32)
    struct.pack_into("<I", hdr, 76, 0x4)
    hdr[80:84] = fourcc
    struct.pack_into("<I", hdr, 104, 0x1000)
    return b"DDS " + bytes(hdr) + pixel_data


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
        native_formats = (BCFormat.BC1, BCFormat.BC1A, BCFormat.BC3, BCFormat.BC4,
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

    def test_dxt3_loads_as_bc2_with_explicit_alpha(self):
        alpha = bytes([0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFE])
        color = struct.pack("<HHI", 0xFFFF, 0x0000, 0)
        tex = Texture.from_dds_bytes(
            _dds_fourcc_bytes(4, 4, b"DXT3", alpha + color),
            name="dxt3",
        )

        rgba, w, h = tex.to_rgba()
        assert tex.format == BCFormat.BC2
        assert (w, h) == (4, 4)
        assert list(rgba[3::4]) == [i * 17 for i in range(16)]

    def test_truncated_dds_payload_is_rejected(self):
        with pytest.raises(ValueError):
            Texture.from_dds_bytes(
                _dds_fourcc_bytes(4, 4, b"DXT1", b"\x00" * 7),
                name="truncated",
            )


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
        native_formats = (BCFormat.BC1, BCFormat.BC1A, BCFormat.BC3, BCFormat.BC4,
                          BCFormat.BC5, BCFormat.BC7, BCFormat.A8R8G8B8)
        for fmt in native_formats:
            tex = Texture.from_image(str(png_64), format=fmt)
            rgba, w, h = tex.to_rgba()
            assert len(rgba) == w * h * 4

    def test_opaque_bc1_does_not_emit_punchthrough_alpha(self):
        pixels = bytearray()
        for i in range(16 * 16):
            v = (i * 37) % 40
            pixels.extend((v, v, v, 255))

        tex = Texture.from_bytes(
            _png_rgba_bytes(16, 16, bytes(pixels)),
            format=BCFormat.BC1,
            generate_mipmaps=False,
            quality=1.0,
        )
        rgba, _, _ = tex.to_rgba()

        assert set(rgba[3::4]) == {255}

    def test_bc1a_preserves_binary_alpha(self):
        pixels = bytearray()
        for i in range(16 * 16):
            alpha = 0 if i % 3 == 0 else 255
            pixels.extend((255, 0, 0, alpha))

        tex = Texture.from_bytes(
            _png_rgba_bytes(16, 16, bytes(pixels)),
            format=BCFormat.BC1A,
            generate_mipmaps=False,
        )
        rgba, _, _ = tex.to_rgba()

        assert tex.format == BCFormat.BC1A
        assert set(rgba[3::4]) == {0, 255}
        assert tex.has_transparency() is True

    def test_bc1a_dds_reads_back_as_bc1(self):
        pixels = bytes((255, 0, 0, 0)) * (4 * 4)
        tex = Texture.from_bytes(
            _png_rgba_bytes(4, 4, pixels),
            format=BCFormat.BC1A,
            generate_mipmaps=False,
        )

        loaded = Texture.from_dds_bytes(tex.to_dds_bytes(), name="bc1a")
        rgba, _, _ = loaded.to_rgba()

        assert loaded.format == BCFormat.BC1
        assert set(rgba[3::4]) == {0}

    def test_bc1_default_drops_source_alpha(self):
        pixels = bytes((255, 0, 0, 0)) * (4 * 4)

        tex = Texture.from_bytes(
            _png_rgba_bytes(4, 4, pixels),
            format=BCFormat.BC1,
            generate_mipmaps=False,
        )
        rgba, _, _ = tex.to_rgba()

        assert set(rgba[3::4]) == {255}
        assert tex.has_transparency() is False


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


class TestFixTextures:
    def test_opaque_bc3_to_bc1(self, png_64):
        """Opaque texture in BC3 should be fixed to BC1."""
        tex = Texture.from_image(str(png_64), format=BCFormat.BC3, name="opaque")
        td = ITD(game=Game.GTA5)
        td.add(tex)
        report = td.fix_textures()
        assert len(report) == 1
        assert "BC3→BC1" in report[0]["fixes"][0]
        assert td.textures[0].format == BCFormat.BC1

    def test_transparent_bc1_to_bc3(self):
        """Transparent texture in BC1 should be fixed to BC3."""
        block = struct.pack("<HHI", 0, 0, 0xFFFFFFFF)
        tex = Texture.from_dds_bytes(
            _dds_fourcc_bytes(4, 4, b"DXT1", block), name="alpha")
        td = ITD(game=Game.GTA5)
        td.add(tex)
        report = td.fix_textures()
        assert len(report) == 1
        assert "BC1→BC3" in report[0]["fixes"][0]
        assert td.textures[0].format == BCFormat.BC3

    def test_missing_mipmaps(self, png_64):
        """Texture with 1 mip on a 64x64 should get mipmaps added."""
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1,
                                 generate_mipmaps=False, name="nomips")
        td = ITD(game=Game.GTA5)
        td.add(tex)
        assert td.textures[0].mip_count == 1
        report = td.fix_textures()
        assert len(report) == 1
        assert any("mipmaps" in f for f in report[0]["fixes"])
        assert td.textures[0].mip_count > 1

    def test_already_correct(self, png_64):
        """Texture that's already fine should not be modified."""
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="good")
        td = ITD(game=Game.GTA5)
        td.add(tex)
        report = td.fix_textures()
        assert len(report) == 0

    def test_returns_report(self, png_64):
        """Report lists only modified textures."""
        t1 = Texture.from_image(str(png_64), format=BCFormat.BC1, name="ok")
        block = struct.pack("<HHI", 0, 0, 0xFFFFFFFF)
        t2 = Texture.from_dds_bytes(
            _dds_fourcc_bytes(4, 4, b"DXT1", block), name="fix_me")
        td = ITD(game=Game.GTA5)
        td.add(t1)
        td.add(t2)
        report = td.fix_textures()
        assert len(report) == 1
        assert report[0]["name"] == "fix_me"


class TestValidate:
    def test_valid_texture(self, png_64):
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="valid")
        warnings = tex.validate()
        assert isinstance(warnings, list)
