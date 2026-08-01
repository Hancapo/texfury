"""texfury — Fast image-to-DDS conversion and texture dictionary toolkit."""

from texfury.alpha import AlphaEdgeMipReport, AlphaEdgeReport
from texfury.formats import BCFormat, MipFilter, RscCompression, suggest_format
from texfury.texture import Texture
from texfury.texture_dict import (
    ITD,
    Game,
    batch_convert,
    create_dict_from_folder,
    extract_dict,
)
from texfury.utils import (
    fit_dimensions,
    has_transparency,
    image_dimensions,
    is_power_of_two,
    next_power_of_two,
    pot_dimensions,
    resize_image,
    resize_image_to_max,
)

__version__ = "1.6.3"

__all__ = [
    "ITD",
    "AlphaEdgeMipReport",
    "AlphaEdgeReport",
    "BCFormat",
    "Game",
    "MipFilter",
    "RscCompression",
    "Texture",
    "batch_convert",
    "create_dict_from_folder",
    "extract_dict",
    "fit_dimensions",
    "has_transparency",
    "image_dimensions",
    "is_power_of_two",
    "next_power_of_two",
    "pot_dimensions",
    "resize_image",
    "resize_image_to_max",
    "suggest_format",
]
