"""texfury — Fast image-to-DDS conversion and texture dictionary toolkit."""

from texfury.formats import BCFormat, MipFilter, RscCompression, suggest_format
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

__version__ = "1.5.1"

__all__ = [
    "BCFormat",
    "MipFilter",
    "RscCompression",
    "suggest_format",
    "Texture",
    "Game",
    "ITD",
    "create_dict_from_folder",
    "batch_convert",
    "extract_dict",
    "has_transparency",
    "is_power_of_two",
    "next_power_of_two",
    "pot_dimensions",
    "image_dimensions",
]
