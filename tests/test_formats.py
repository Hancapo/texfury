"""Test format helpers and suggest_format logic."""

from texfury.formats import (
    BCFormat, suggest_format,
    is_block_compressed, block_byte_size, mip_data_size,
    total_mip_data_size, row_pitch,
    BC_TO_DXGI, DXGI_TO_BC,
    BC_TO_DX9, DX9_TO_BC,
    BC_TO_RSC8, RSC8_TO_BC,
    BC_TO_RSC5, RSC5_TO_BC,
    _GTA4_UNSUPPORTED,
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
    def test_bc_formats_are_compressed(self):
        for fmt in (BCFormat.BC1, BCFormat.BC3, BCFormat.BC4, BCFormat.BC5, BCFormat.BC7):
            assert is_block_compressed(fmt)

    def test_a8r8g8b8_is_not_compressed(self):
        assert not is_block_compressed(BCFormat.A8R8G8B8)


class TestBlockByteSize:
    def test_8_byte_formats(self):
        assert block_byte_size(BCFormat.BC1) == 8
        assert block_byte_size(BCFormat.BC4) == 8

    def test_16_byte_formats(self):
        assert block_byte_size(BCFormat.BC3) == 16
        assert block_byte_size(BCFormat.BC5) == 16
        assert block_byte_size(BCFormat.BC7) == 16


class TestMipDataSize:
    def test_bc1_256x256(self):
        # 64x64 blocks * 8 bytes
        assert mip_data_size(256, 256, BCFormat.BC1) == 32768

    def test_a8r8g8b8_256x256(self):
        assert mip_data_size(256, 256, BCFormat.A8R8G8B8) == 256 * 256 * 4

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
    def test_uncompressed(self):
        assert row_pitch(256, BCFormat.A8R8G8B8) == 256 * 4

    def test_bc1(self):
        # 256 / 4 = 64 blocks * 8 bytes
        assert row_pitch(256, BCFormat.BC1) == 512


class TestFormatMappings:
    def test_dxgi_roundtrip(self):
        for bc, dxgi in BC_TO_DXGI.items():
            assert DXGI_TO_BC[dxgi] == bc

    def test_dx9_roundtrip(self):
        for bc, dx9 in BC_TO_DX9.items():
            assert DX9_TO_BC[dx9] == bc

    def test_rsc8_roundtrip(self):
        for bc, rsc8 in BC_TO_RSC8.items():
            assert RSC8_TO_BC[rsc8] == bc

    def test_rsc5_coverage(self):
        # RSC5 only supports BC1, BC3, A8R8G8B8
        assert BCFormat.BC1 in BC_TO_RSC5
        assert BCFormat.BC3 in BC_TO_RSC5
        assert BCFormat.A8R8G8B8 in BC_TO_RSC5
        assert BCFormat.BC4 not in BC_TO_RSC5
        assert BCFormat.BC5 not in BC_TO_RSC5
        assert BCFormat.BC7 not in BC_TO_RSC5

    def test_gta4_unsupported(self):
        assert BCFormat.BC4 in _GTA4_UNSUPPORTED
        assert BCFormat.BC5 in _GTA4_UNSUPPORTED
        assert BCFormat.BC7 in _GTA4_UNSUPPORTED
        assert BCFormat.BC1 not in _GTA4_UNSUPPORTED
