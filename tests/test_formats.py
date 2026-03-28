"""Test format helpers and suggest_format logic."""

from texfury.formats import (
    BCFormat, suggest_format,
    is_block_compressed, block_byte_size, pixel_byte_size,
    mip_data_size, total_mip_data_size, row_pitch,
    BC_TO_DXGI, DXGI_TO_BC,
    BC_TO_DX9, DX9_TO_BC,
    BC_TO_RSC8, RSC8_TO_BC,
    BC_TO_RSC5, RSC5_TO_BC,
    _GTA4_UNSUPPORTED,
    _BLOCK_COMPRESSED, _PIXEL_BYTES,
)


class TestSuggestFormat:
    def test_opaque_quality(self):
        assert suggest_format(False) == BCFormat.BC7

    def test_opaque_size(self):
        assert suggest_format(False, quality_over_size=False) == BCFormat.BC1

    def test_alpha_quality(self):
        assert suggest_format(True) == BCFormat.BC7

    def test_alpha_size(self):
        assert suggest_format(True, quality_over_size=False) == BCFormat.BC3

    def test_normal_map(self):
        assert suggest_format(False, normal_map=True) == BCFormat.BC5

    def test_single_channel(self):
        assert suggest_format(False, single_channel=True) == BCFormat.BC4


class TestBlockCompressed:
    def test_all_bc_formats_are_compressed(self):
        for fmt in (BCFormat.BC1, BCFormat.BC2, BCFormat.BC3,
                    BCFormat.BC4, BCFormat.BC5, BCFormat.BC6H, BCFormat.BC7):
            assert is_block_compressed(fmt), f"{fmt.name} should be block compressed"

    def test_uncompressed_formats(self):
        for fmt in (BCFormat.A8R8G8B8, BCFormat.R8G8B8A8, BCFormat.R8, BCFormat.A8,
                    BCFormat.R8G8, BCFormat.B5G6R5, BCFormat.B5G5R5A1,
                    BCFormat.R10G10B10A2, BCFormat.R16_FLOAT, BCFormat.R16G16_FLOAT,
                    BCFormat.R16G16B16A16_FLOAT, BCFormat.R32_FLOAT,
                    BCFormat.R32G32B32A32_FLOAT):
            assert not is_block_compressed(fmt), f"{fmt.name} should NOT be block compressed"


class TestBlockByteSize:
    def test_8_byte_formats(self):
        assert block_byte_size(BCFormat.BC1) == 8
        assert block_byte_size(BCFormat.BC4) == 8

    def test_16_byte_formats(self):
        assert block_byte_size(BCFormat.BC2) == 16
        assert block_byte_size(BCFormat.BC3) == 16
        assert block_byte_size(BCFormat.BC5) == 16
        assert block_byte_size(BCFormat.BC6H) == 16
        assert block_byte_size(BCFormat.BC7) == 16


class TestPixelByteSize:
    def test_4_byte_formats(self):
        assert pixel_byte_size(BCFormat.A8R8G8B8) == 4
        assert pixel_byte_size(BCFormat.R8G8B8A8) == 4
        assert pixel_byte_size(BCFormat.R10G10B10A2) == 4
        assert pixel_byte_size(BCFormat.R16G16_FLOAT) == 4
        assert pixel_byte_size(BCFormat.R32_FLOAT) == 4

    def test_2_byte_formats(self):
        assert pixel_byte_size(BCFormat.B5G6R5) == 2
        assert pixel_byte_size(BCFormat.B5G5R5A1) == 2
        assert pixel_byte_size(BCFormat.R8G8) == 2
        assert pixel_byte_size(BCFormat.R16_FLOAT) == 2

    def test_1_byte_formats(self):
        assert pixel_byte_size(BCFormat.R8) == 1
        assert pixel_byte_size(BCFormat.A8) == 1

    def test_8_byte_formats(self):
        assert pixel_byte_size(BCFormat.R16G16B16A16_FLOAT) == 8

    def test_16_byte_formats(self):
        assert pixel_byte_size(BCFormat.R32G32B32A32_FLOAT) == 16

    def test_all_uncompressed_have_pixel_size(self):
        for fmt in BCFormat:
            if not is_block_compressed(fmt):
                assert fmt in _PIXEL_BYTES, f"{fmt.name} missing from _PIXEL_BYTES"


class TestMipDataSize:
    def test_bc1_256x256(self):
        # 64x64 blocks * 8 bytes
        assert mip_data_size(256, 256, BCFormat.BC1) == 32768

    def test_bc7_256x256(self):
        # 64x64 blocks * 16 bytes
        assert mip_data_size(256, 256, BCFormat.BC7) == 65536

    def test_a8r8g8b8_256x256(self):
        assert mip_data_size(256, 256, BCFormat.A8R8G8B8) == 256 * 256 * 4

    def test_r8_256x256(self):
        assert mip_data_size(256, 256, BCFormat.R8) == 256 * 256

    def test_r16g16b16a16_float_64x64(self):
        assert mip_data_size(64, 64, BCFormat.R16G16B16A16_FLOAT) == 64 * 64 * 8

    def test_small_mip_minimum_block(self):
        # 1x1 should still be at least one block
        assert mip_data_size(1, 1, BCFormat.BC1) == 8

    def test_total_mip_data_size(self):
        total = total_mip_data_size(256, 256, BCFormat.BC1, 1)
        assert total == mip_data_size(256, 256, BCFormat.BC1)

        total2 = total_mip_data_size(256, 256, BCFormat.BC1, 2)
        assert total2 == (
            mip_data_size(256, 256, BCFormat.BC1)
            + mip_data_size(128, 128, BCFormat.BC1)
        )


class TestRowPitch:
    def test_uncompressed_4bpp(self):
        assert row_pitch(256, BCFormat.A8R8G8B8) == 256 * 4

    def test_uncompressed_1bpp(self):
        assert row_pitch(256, BCFormat.R8) == 256

    def test_uncompressed_2bpp(self):
        assert row_pitch(256, BCFormat.B5G6R5) == 256 * 2

    def test_bc1(self):
        # 256 / 4 = 64 blocks * 8 bytes
        assert row_pitch(256, BCFormat.BC1) == 512

    def test_bc7(self):
        # 256 / 4 = 64 blocks * 16 bytes
        assert row_pitch(256, BCFormat.BC7) == 1024


class TestFormatMappings:
    def test_dxgi_roundtrip(self):
        for bc, dxgi in BC_TO_DXGI.items():
            assert DXGI_TO_BC[dxgi] == bc

    def test_dxgi_covers_all_formats(self):
        for fmt in BCFormat:
            assert fmt in BC_TO_DXGI, f"{fmt.name} missing from BC_TO_DXGI"

    def test_dx9_roundtrip(self):
        for bc, dx9 in BC_TO_DX9.items():
            assert DX9_TO_BC[dx9] == bc

    def test_rsc8_roundtrip(self):
        for bc, rsc8 in BC_TO_RSC8.items():
            assert RSC8_TO_BC[rsc8] == bc

    def test_rsc8_covers_all_formats(self):
        for fmt in BCFormat:
            assert fmt in BC_TO_RSC8, f"{fmt.name} missing from BC_TO_RSC8"

    def test_rsc5_coverage(self):
        assert BCFormat.BC1 in BC_TO_RSC5
        assert BCFormat.BC2 in BC_TO_RSC5
        assert BCFormat.BC3 in BC_TO_RSC5
        assert BCFormat.A8R8G8B8 in BC_TO_RSC5
        assert BCFormat.R8 in BC_TO_RSC5
        assert BCFormat.A8 in BC_TO_RSC5

    def test_gta4_unsupported(self):
        assert BCFormat.BC4 in _GTA4_UNSUPPORTED
        assert BCFormat.BC5 in _GTA4_UNSUPPORTED
        assert BCFormat.BC6H in _GTA4_UNSUPPORTED
        assert BCFormat.BC7 in _GTA4_UNSUPPORTED
        assert BCFormat.BC1 not in _GTA4_UNSUPPORTED
        assert BCFormat.A8R8G8B8 not in _GTA4_UNSUPPORTED

    def test_rsc8_srgb_variants(self):
        """SRGB variants should map to the same BCFormat as UNORM."""
        from texfury.formats import Rsc8TextureFormat
        assert RSC8_TO_BC[Rsc8TextureFormat.BC1_UNORM_SRGB] == BCFormat.BC1
        assert RSC8_TO_BC[Rsc8TextureFormat.BC2_UNORM_SRGB] == BCFormat.BC2
        assert RSC8_TO_BC[Rsc8TextureFormat.BC3_UNORM_SRGB] == BCFormat.BC3
        assert RSC8_TO_BC[Rsc8TextureFormat.BC7_UNORM_SRGB] == BCFormat.BC7
        assert RSC8_TO_BC[Rsc8TextureFormat.R8G8B8A8_UNORM_SRGB] == BCFormat.R8G8B8A8
        assert RSC8_TO_BC[Rsc8TextureFormat.B8G8R8A8_UNORM_SRGB] == BCFormat.A8R8G8B8
