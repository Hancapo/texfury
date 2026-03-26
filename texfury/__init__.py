"""texfury — Fast image-to-DDS conversion and YTD texture dictionaries."""

from texfury.formats import BCFormat, MipFilter, suggest_format
from texfury.texture import Texture
from texfury.ytd import (
    Game,
    ITD,
    create_ytd_from_folder,
    batch_convert,
    extract_ytd,
)
from texfury.utils import (
    has_transparency,
    is_power_of_two,
    next_power_of_two,
    pot_dimensions,
    image_dimensions,
)

__version__ = "1.3.1"

__all__ = [
    "BCFormat",
    "MipFilter",
    "suggest_format",
    "Texture",
    "Game",
    "ITD",
    "create_ytd_from_folder",
    "batch_convert",
    "extract_ytd",
    "has_transparency",
    "is_power_of_two",
    "next_power_of_two",
    "pot_dimensions",
    "image_dimensions",
]
