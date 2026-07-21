"""Internal Texture Dictionary (ITD) — unified texture dictionary handling for RAGE games."""

from __future__ import annotations

import logging
import struct
from enum import Enum
from pathlib import Path
from typing import Callable

from texfury.formats import (
    BCFormat, MipFilter, RscCompression, _GTA4_UNSUPPORTED,
    is_block_compressed,
)
from texfury.rsc import (
    RSC5_MAGIC, RSC7_MAGIC, RSC8_MAGIC, parse_rsc7_header,
)
from texfury.texture import Texture
from texfury.dictionary_codecs.common import (
    _decompress_rsc7_padded, _looks_like_gtav_ps3_virtual,
)

log = logging.getLogger("texfury")


# ── Game enum ────────────────────────────────────────────────────────────────

class Game(str, Enum):
    """Target game / edition for texture dictionaries."""
    GTA4 = "gta4"
    GTA5 = "gta5"
    GTA5_PS3 = "gta5_ps3"
    GTA5_GEN9 = "gta5_enhanced"
    RDR2 = "rdr2"


# ── Shared helpers ───────────────────────────────────────────────────────────







def _texture_output_path(output_dir: Path, name: str) -> Path:
    """Return a safe, direct child path for an extracted texture."""
    if not name or "/" in name or "\\" in name:
        raise ValueError(f"Unsafe texture name for extraction: {name!r}")

    output_root = output_dir.resolve()
    candidate = (output_root / f"{name}.dds").resolve()
    if candidate.parent != output_root:
        raise ValueError(f"Unsafe texture name for extraction: {name!r}")
    return candidate


def _detect_game(file_data: bytes) -> Game:
    """Detect game from the RSC magic bytes and version."""
    if len(file_data) < 12:
        raise ValueError("File too short to detect format")
    magic = struct.unpack_from("<I", file_data, 0)[0]
    if magic == RSC5_MAGIC:
        return Game.GTA4
    if magic == RSC7_MAGIC:
        version = struct.unpack_from("<I", file_data, 4)[0]
        if version == 5:
            return Game.GTA5_GEN9
        return Game.GTA5
    if magic == RSC8_MAGIC:
        return Game.RDR2
    raise ValueError(f"Unknown texture dictionary format — magic: 0x{magic:08X}")




def _is_gtav_ps3_ctd(file_data: bytes) -> bool:
    try:
        version, _, _ = parse_rsc7_header(file_data)
        if version != 13:
            return False
        virtual_data, _ = _decompress_rsc7_padded(file_data)
    except Exception:
        return False

    return _looks_like_gtav_ps3_virtual(virtual_data)




def _should_parse_gtav_ps3(path: Path, file_data: bytes) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".ctd":
        return True
    if suffix in {".ytd", ".wtd"}:
        return False
    return _is_gtav_ps3_ctd(file_data)










IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tiff",
                    ".tif", ".webp", ".psd", ".gif", ".hdr"}


# ── ITD ──────────────────────────────────────────────────────────────────

class ITD:
    """Internal Texture Dictionary — generic abstraction over RAGE texture
    dictionary formats (.wtd for x32, .ytd for x64).

    Usage:
        td = ITD()                          # GTA V Legacy by default
        td = ITD(game=Game.GTA4)            # GTA IV (.wtd)
        td = ITD(game=Game.GTA5_GEN9)   # GTA V Enhanced
        td = ITD(game=Game.RDR2)            # RDR2
        td = ITD.load("existing.ctd")       # GTA V PS3 read-only

        td.add(Texture.from_image("logo.png"))
        td.save("output.ytd")

        td = ITD.load("existing.ytd")       # auto-detects game
    """

    __slots__ = ("_textures", "_game")

    def __init__(self, game: Game = Game.GTA5) -> None:
        self._textures: list[Texture] = []
        self._game: Game = game

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def game(self) -> Game:
        return self._game

    @property
    def textures(self) -> list[Texture]:
        return list(self._textures)

    # ── Mutation ────────────────────────────────────────────────────────

    def add(self, texture: Texture) -> None:
        """Add a texture to the dictionary."""
        if not texture.name:
            raise ValueError("Texture must have a name before adding to a dictionary")
        log.debug("add: %s (%s %dx%d)", texture.name, texture.format.name, texture.width, texture.height)
        self._textures.append(texture)

    def replace(self, name: str, texture: Texture) -> None:
        """Replace a texture by name. Raises KeyError if not found."""
        lower = name.lower()
        for i, t in enumerate(self._textures):
            if t.name.lower() == lower:
                if texture.name != t.name:
                    texture.name = t.name
                self._textures[i] = texture
                return
        raise KeyError(f"Texture '{name}' not found in dictionary")

    def remove(self, name: str) -> None:
        """Remove a texture by name. Raises KeyError if not found."""
        lower = name.lower()
        for i, t in enumerate(self._textures):
            if t.name.lower() == lower:
                self._textures.pop(i)
                return
        raise KeyError(f"Texture '{name}' not found in dictionary")

    def merge(self, other: ITD, *, overwrite: bool = False) -> None:
        """Merge textures from another dictionary into this one.

        Parameters
        ----------
        other : ITD
            Source dictionary to merge from.
        overwrite : bool
            If True, textures with duplicate names are replaced.
            If False (default), duplicates are skipped.
        """
        existing = {t.name.lower() for t in self._textures}
        for tex in other.textures:
            lower = tex.name.lower()
            if lower in existing:
                if overwrite:
                    self.replace(tex.name, tex)
                    log.debug("merge: replaced %s", tex.name)
                else:
                    log.debug("merge: skipped duplicate %s", tex.name)
                continue
            self._textures.append(tex)
            existing.add(lower)
            log.debug("merge: added %s", tex.name)

    @staticmethod
    def merge_many(
        paths: list[str | Path],
        *,
        game: Game | None = None,
        overwrite: bool = False,
    ) -> ITD:
        """Load and merge multiple texture dictionaries into one.

        Parameters
        ----------
        paths : list of str or Path
            Paths to texture dictionaries to merge.
        game : Game, optional
            Target game format. If None, uses the game of the first file.
        overwrite : bool
            If True, later files overwrite earlier duplicates.
            If False (default), first occurrence wins.
        """
        if not paths:
            raise ValueError("paths must not be empty")
        result = ITD.load(paths[0])
        if game is not None:
            result._game = game
        log.info("merge_many: starting with %s (%d textures)", paths[0], len(result))
        for p in paths[1:]:
            other = ITD.load(p)
            result.merge(other, overwrite=overwrite)
            log.info("merge_many: merged %s (%d textures)", p, len(other))
        return result

    # ── Lookup ──────────────────────────────────────────────────────────

    def get(self, name: str) -> Texture:
        """Get a texture by name. Raises KeyError if not found."""
        lower = name.lower()
        for t in self._textures:
            if t.name.lower() == lower:
                return t
        raise KeyError(f"Texture '{name}' not found in dictionary")

    def names(self) -> list[str]:
        """Return the names of all textures."""
        return [t.name for t in self._textures]

    # ── I/O ─────────────────────────────────────────────────────────────

    def save(self, path: str | Path, *,
             compression: RscCompression | None = None) -> None:
        """Build and write the texture dictionary to a file.

        *compression* only applies to RDR2 (RSC8).  Defaults to
        :attr:`RscCompression.OODLE` for RDR2 and is ignored for other games.
        """
        from texfury.dictionary_codecs.gta4 import _build_gta4
        from texfury.dictionary_codecs.gta5 import _build_gtav
        from texfury.dictionary_codecs.enhanced import _build_enhanced
        from texfury.dictionary_codecs.rdr2 import _build_rdr2

        log.info("save: %s (%s, %d textures)", path, self._game.value, len(self._textures))
        if self._game == Game.RDR2:
            if compression is None:
                compression = RscCompression.OODLE
            data = _build_rdr2(self._textures, compression=compression)
        else:
            if self._game == Game.GTA5_PS3:
                raise NotImplementedError("Writing GTA V PS3 .ctd files is not supported")
            builders = {
                Game.GTA4: _build_gta4,
                Game.GTA5: _build_gtav,
                Game.GTA5_GEN9: _build_enhanced,
            }
            data = builders[self._game](self._textures)
        Path(path).write_bytes(data)
        log.info("save: wrote %d bytes", len(data))

    @staticmethod
    def load(path: str | Path) -> ITD:
        """Read a texture dictionary — auto-detects game from header."""
        from texfury.dictionary_codecs.gta4 import _parse_gta4
        from texfury.dictionary_codecs.gta5 import _parse_gtav
        from texfury.dictionary_codecs.gta5_ps3 import _parse_gtav_ps3
        from texfury.dictionary_codecs.enhanced import _parse_enhanced
        from texfury.dictionary_codecs.rdr2 import _parse_rdr2

        log.info("load: %s", path)
        path = Path(path)
        file_data = path.read_bytes()
        game = _detect_game(file_data)
        if game == Game.GTA5 and _should_parse_gtav_ps3(path, file_data):
            game = Game.GTA5_PS3
        log.debug("load: detected game=%s, %d bytes", game.value, len(file_data))
        parsers = {
            Game.GTA4: _parse_gta4,
            Game.GTA5: _parse_gtav,
            Game.GTA5_PS3: _parse_gtav_ps3,
            Game.GTA5_GEN9: _parse_enhanced,
            Game.RDR2: _parse_rdr2,
        }
        return parsers[game](file_data)

    @classmethod
    def from_folder(
        cls,
        folder: str | Path,
        *,
        game: Game = Game.GTA5,
        format: BCFormat = BCFormat.BC7,
        quality: float = 0.7,
        generate_mipmaps: bool = True,
        min_mip_size: int = 4,
        mip_filter: MipFilter = MipFilter.MITCHELL,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> ITD:
        """Build a texture dictionary from all images in a folder.

        Returns the populated ITD without writing to disk.
        Call ``.save(path)`` afterwards to write the file.
        """
        folder = Path(folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"Not a directory: {folder}")

        files = sorted(
            f for f in folder.iterdir()
            if f.suffix.lower() in IMAGE_EXTENSIONS or f.suffix.lower() == ".dds"
        )
        if not files:
            raise FileNotFoundError(f"No image files found in {folder}")

        td = cls(game=game)
        total = len(files)
        for i, f in enumerate(files):
            name = f.stem.lower()
            if on_progress:
                on_progress(i + 1, total, name)
            if f.suffix.lower() == ".dds":
                tex = Texture.from_dds(f, name=name)
            else:
                tex = Texture.from_image(f, format=format, quality=quality,
                                         generate_mipmaps=generate_mipmaps,
                                         min_mip_size=min_mip_size,
                                         mip_filter=mip_filter, name=name)
            td.add(tex)
        return td

    def extract(self, output_dir: str | Path) -> Path:
        """Extract all textures to DDS files in the given directory.

        Returns the output directory path.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        output_paths = [
            _texture_output_path(out, tex.name) for tex in self._textures
        ]
        for tex, output_path in zip(self._textures, output_paths):
            tex.save_dds(output_path)
        return out

    @staticmethod
    def inspect(path: str | Path) -> list[dict]:
        """Read texture metadata without loading pixel data. Auto-detects game."""
        from texfury.dictionary_codecs.gta4 import _inspect_gta4
        from texfury.dictionary_codecs.gta5 import _inspect_gtav
        from texfury.dictionary_codecs.gta5_ps3 import _inspect_gtav_ps3
        from texfury.dictionary_codecs.enhanced import _inspect_enhanced
        from texfury.dictionary_codecs.rdr2 import _inspect_rdr2

        path = Path(path)
        file_data = path.read_bytes()
        game = _detect_game(file_data)
        if game == Game.GTA5 and _should_parse_gtav_ps3(path, file_data):
            game = Game.GTA5_PS3
        inspectors = {
            Game.GTA4: _inspect_gta4,
            Game.GTA5: _inspect_gtav,
            Game.GTA5_PS3: _inspect_gtav_ps3,
            Game.GTA5_GEN9: _inspect_enhanced,
            Game.RDR2: _inspect_rdr2,
        }
        return inspectors[game](file_data)

    # ── Fix / optimize ───────────────────────────────────────────────

    def fix_textures(
        self,
        *,
        quality: float = 0.7,
        min_mip_size: int = 4,
        mip_filter: MipFilter = MipFilter.MITCHELL,
        ignore: set[str] | list[str] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> list[dict]:
        """Fix common texture issues in-place.

        For each texture, checks and corrects:
        - **Non-power-of-two** dimensions → resized to nearest POT.
        - **Missing mipmaps** → regenerated (expected mips for ≥8×8 textures).
        - **Format choice** → BC1 for opaque textures, BC3 for transparent
          (only if current format is a BC type that doesn't match).

        Returns a list of dicts describing what was fixed, one per
        texture that was modified.  Unmodified textures are omitted.

        Parameters
        ----------
        quality : float
            Compression quality for recompressed textures.
        min_mip_size : int
            Minimum dimension for the smallest mip level.
        mip_filter : MipFilter
            Downsampling filter for mipmap generation and POT resize.
        ignore : set or list of str, optional
            Texture names to skip.  These textures will not be
            inspected or modified.
        on_progress : callable, optional
            ``(current, total, texture_name)`` callback.
        """
        from texfury import _native as native

        report: list[dict] = []
        total = len(self._textures)
        skip = set(ignore) if ignore else set()

        for idx, tex in enumerate(self._textures):
            if on_progress:
                on_progress(idx + 1, total, tex.name)

            if tex.name in skip:
                continue

            fixes: list[str] = []

            # Determine expected mip count
            w, h = tex.width, tex.height
            expected_mips = 1
            dim = max(w, h)
            while dim > min_mip_size:
                dim //= 2
                expected_mips += 1

            needs_pot = not tex.is_power_of_two
            needs_mips = tex.mip_count < expected_mips and max(w, h) >= 8

            # Only suggest format change for BC formats
            needs_format = False
            suggested_fmt = tex.format
            if is_block_compressed(tex.format):
                transparent = tex.has_transparency()
                if transparent and tex.format == BCFormat.BC1:
                    suggested_fmt = BCFormat.BC3
                    needs_format = True
                    fixes.append(f"format BC1→BC3 (has transparency)")
                elif not transparent and tex.format in (
                    BCFormat.BC1A, BCFormat.BC3, BCFormat.BC7,
                ):
                    suggested_fmt = BCFormat.BC1
                    needs_format = True
                    fixes.append(f"format {tex.format.name}→BC1 (opaque)")

            if needs_pot:
                fixes.append("resize to power-of-two")
            if needs_mips:
                fixes.append(f"mipmaps {tex.mip_count}→{expected_mips}")

            if not fixes:
                continue

            # Decompress → recompress with fixes
            rgba, rw, rh = tex.to_rgba(0)
            img = native.create_image(rw, rh, rgba)
            try:
                new_tex = Texture._compress_image(
                    img,
                    format=suggested_fmt,
                    quality=quality,
                    generate_mipmaps=True,
                    min_mip_size=min_mip_size,
                    resize_to_pot=True,
                    mip_filter=mip_filter,
                    name=tex.name,
                )
            finally:
                native.free_image(img)

            self._textures[idx] = new_tex
            log.info("fix_textures: %s → %s", tex.name, ", ".join(fixes))
            report.append({"name": tex.name, "fixes": fixes})

        return report

    def convert(
        self,
        game: Game,
        *,
        quality: float = 0.7,
        generate_mipmaps: bool = True,
        min_mip_size: int = 4,
        mip_filter: MipFilter = MipFilter.MITCHELL,
    ) -> list[dict]:
        """Convert this dictionary to a different game format in-place.

        Textures using formats unsupported by the target game are
        recompressed automatically (e.g. BC7 → BC1 for GTA IV).

        Parameters
        ----------
        game : Game
            Target game format.
        quality : float
            Compression quality for recompressed textures.
        generate_mipmaps : bool
            Regenerate mipmaps for recompressed textures.
        min_mip_size : int
            Minimum dimension for the smallest mip level.
        mip_filter : MipFilter
            Downsampling filter for mipmap generation.

        Returns
        -------
        list of dict
            One entry per recompressed texture: ``{"name": str, "old_format": str, "new_format": str}``.
        """
        from texfury import _native as native

        log.info("convert: %s → %s", self._game.value, game.value)
        self._game = game

        if game != Game.GTA4:
            return []

        report: list[dict] = []
        for idx, tex in enumerate(self._textures):
            if tex.format not in _GTA4_UNSUPPORTED:
                continue

            # Pick replacement format
            old_name = tex.format.name
            if tex.format in (BCFormat.BC4, BCFormat.BC5, BCFormat.BC6H):
                new_fmt = BCFormat.BC1
            elif tex.format == BCFormat.BC7:
                transparent = tex.has_transparency()
                new_fmt = BCFormat.BC3 if transparent else BCFormat.BC1
            else:
                # Uncompressed formats not supported by GTA4 → A8R8G8B8
                new_fmt = BCFormat.A8R8G8B8

            log.info("convert: %s %s → %s", tex.name, old_name, new_fmt.name)
            rgba, w, h = tex.to_rgba(0)
            img = native.create_image(w, h, rgba)
            try:
                new_tex = Texture._compress_image(
                    img,
                    format=new_fmt,
                    quality=quality,
                    generate_mipmaps=generate_mipmaps,
                    min_mip_size=min_mip_size,
                    resize_to_pot=True,
                    mip_filter=mip_filter,
                    name=tex.name,
                )
            finally:
                native.free_image(img)

            self._textures[idx] = new_tex
            report.append({"name": tex.name, "old_format": old_name, "new_format": new_fmt.name})

        return report

    # ── Dunder ──────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._textures)

    def __iter__(self):
        return iter(self._textures)

    def __getitem__(self, name: str) -> Texture:
        """Lookup by name: ``td["body_d"]``."""
        return self.get(name)

    def __contains__(self, name: str) -> bool:
        lower = name.lower()
        return any(t.name.lower() == lower for t in self._textures)

    def __repr__(self) -> str:
        count = len(self._textures)
        summary = ", ".join(t.name for t in self._textures[:5])
        if count > 5:
            summary += f", ... (+{count - 5} more)"
        return f"ITD(game={self._game.value!r}, textures={count}, [{summary}])"


# ── Convenience functions ────────────────────────────────────────────────────

def create_dict_from_folder(
    folder: str | Path,
    output: str | Path | None = None,
    *,
    game: Game = Game.GTA5,
    format: BCFormat = BCFormat.BC1,
    quality: float = 0.7,
    generate_mipmaps: bool = True,
    min_mip_size: int = 4,
    mip_filter: MipFilter = MipFilter.MITCHELL,
    compression: RscCompression | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> ITD:
    """Create a texture dictionary from all images in a folder.

    If *output* is given the dictionary is saved to disk immediately.
    Otherwise it is only built in memory — call ``td.save(path)`` later.

    *compression* only applies to RDR2 (RSC8).  Defaults to
    :attr:`RscCompression.OODLE` for RDR2 and is ignored for other games.

    Returns the populated :class:`ITD`.
    """
    td = ITD.from_folder(
        folder, game=game, format=format, quality=quality,
        generate_mipmaps=generate_mipmaps, min_mip_size=min_mip_size,
        mip_filter=mip_filter, on_progress=on_progress,
    )
    if output is not None:
        td.save(output, compression=compression)
    return td


def batch_convert(
    folder: str | Path,
    output_dir: str | Path | None = None,
    *,
    format: BCFormat = BCFormat.BC1,
    quality: float = 0.7,
    generate_mipmaps: bool = True,
    min_mip_size: int = 4,
    mip_filter: MipFilter = MipFilter.MITCHELL,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Convert all images in a folder to DDS files."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Not a directory: {folder}")

    if output_dir is None:
        output_dir = folder / "dds_out"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        f for f in folder.iterdir()
        if f.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not files:
        raise FileNotFoundError(f"No image files found in {folder}")

    total = len(files)
    for i, f in enumerate(files):
        name = f.stem.lower()
        if on_progress:
            on_progress(i + 1, total, name)

        tex = Texture.from_image(f, format=format, quality=quality,
                                 generate_mipmaps=generate_mipmaps,
                                 min_mip_size=min_mip_size,
                                 mip_filter=mip_filter, name=name)
        tex.save_dds(output_dir / f"{name}.dds")

    return output_dir


def extract_dict(
    source: ITD | str | Path,
    output_dir: str | Path | None = None,
) -> Path:
    """Extract all textures as DDS files.

    *source* can be an already-loaded :class:`ITD` or a file path (auto-detects game).
    If *output_dir* is omitted, a folder named after the file stem is created
    next to it (or ``extracted/`` when *source* is an ITD).

    Returns the output directory path.
    """
    if isinstance(source, ITD):
        td = source
        if output_dir is None:
            output_dir = Path("extracted")
    else:
        source = Path(source)
        td = ITD.load(source)
        if output_dir is None:
            output_dir = source.parent / source.stem

    return td.extract(output_dir)
