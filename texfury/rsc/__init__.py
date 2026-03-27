"""RAGE resource container formats (RSC5, RSC7, RSC8).

Shared constants and re-exports for all RSC variants.
"""

# Virtual / Physical base addresses — common to all RAGE resource formats.
DAT_VIRTUAL_BASE: int = 0x50000000
DAT_PHYSICAL_BASE: int = 0x60000000
DAT_BASE_SIZE: int = 0x2000

from texfury.rsc.rsc7 import (  # noqa: E402, F401
    RSC7_MAGIC, build_rsc7, decompress_rsc7, parse_rsc7_header,
)
from texfury.rsc.rsc8 import (  # noqa: E402, F401
    RSC8_MAGIC, build_rsc8, decompress_rsc8,
)
