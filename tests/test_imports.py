"""Test that all public API is importable and consistent."""

from texfury import (
    BCFormat, MipFilter, RscCompression, suggest_format,
    Texture,
    Game, ITD,
    create_dict_from_folder, batch_convert, extract_dict,
    create_ytd_from_folder, extract_ytd,
    has_transparency, is_power_of_two, next_power_of_two,
    pot_dimensions, image_dimensions,
)


def test_backward_compatible_aliases():
    assert create_ytd_from_folder is create_dict_from_folder
    assert extract_ytd is extract_dict


def test_game_enum_values():
    assert Game.GTA4.value == "gta4"
    assert Game.GTA5.value == "gta5"
    assert Game.GTA5_GEN9.value == "gta5_enhanced"
    assert Game.RDR2.value == "rdr2"


def test_game_enum_count():
    assert len(Game) == 4


def test_bcformat_block_compressed():
    """All BC formats are present and block-compressed."""
    for name in ("BC1", "BC2", "BC3", "BC4", "BC5", "BC6H", "BC7"):
        assert hasattr(BCFormat, name)


def test_bcformat_uncompressed():
    """Uncompressed formats are present."""
    for name in ("A8R8G8B8", "R8G8B8A8", "R8", "A8", "R8G8",
                 "B5G6R5", "B5G5R5A1", "R10G10B10A2",
                 "R16_FLOAT", "R16G16_FLOAT", "R16G16B16A16_FLOAT",
                 "R32_FLOAT", "R32G32B32A32_FLOAT"):
        assert hasattr(BCFormat, name)


def test_rsc_compression_values():
    assert RscCompression.DEFLATE.value == 1
    assert RscCompression.OODLE.value == 2
    assert len(RscCompression) == 2


def test_mipfilter_values():
    assert len(MipFilter) == 6
