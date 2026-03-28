"""Test that all public API is importable and consistent."""

from texfury import (
    BCFormat, MipFilter, suggest_format,
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


def test_bcformat_values():
    assert BCFormat.BC1.value == 0
    assert BCFormat.BC3.value == 1
    assert BCFormat.BC4.value == 2
    assert BCFormat.BC5.value == 3
    assert BCFormat.BC7.value == 4
    assert BCFormat.A8R8G8B8.value == 5


def test_mipfilter_values():
    assert len(MipFilter) == 6
