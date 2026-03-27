"""texfury — Fast image-to-DDS conversion and texture dictionary toolkit."""

from texfury.formats import BCFormat, MipFilter, suggest_format
from texfury.texture import Texture
from texfury.texture_dict import (
    Game,
    ITD,
    create_dict_from_folder,
    batch_convert,
    extract_dict,
)
from texfury.utils import (
    has_transparency,
    is_power_of_two,
    next_power_of_two,
    pot_dimensions,
    image_dimensions,
)

# Backward-compatible aliases
create_ytd_from_folder = create_dict_from_folder
extract_ytd = extract_dict

__version__ = "1.4.0"

__all__ = [
    "BCFormat",
    "MipFilter",
    "suggest_format",
    "Texture",
    "Game",
    "ITD",
    "create_dict_from_folder",
    "batch_convert",
    "extract_dict",
    # Backward-compatible aliases
    "create_ytd_from_folder",
    "extract_ytd",
    "has_transparency",
    "is_power_of_two",
    "next_power_of_two",
    "pot_dimensions",
    "image_dimensions",
]
