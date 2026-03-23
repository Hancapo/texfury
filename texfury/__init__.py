"""texfury — Fast image-to-DDS conversion and GTA V YTD texture dictionaries."""

from texfury.formats import BCFormat, MipFilter
from texfury.texture import Texture
from texfury.ytd import (
    YTDFile,
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

__version__ = "1.0.0"

__all__ = [
    "BCFormat",
    "MipFilter",
    "Texture",
    "YTDFile",
    "create_ytd_from_folder",
    "batch_convert",
    "extract_ytd",
    "has_transparency",
    "is_power_of_two",
    "next_power_of_two",
    "pot_dimensions",
    "image_dimensions",
]
