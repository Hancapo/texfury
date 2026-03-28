"""Test ITD (Internal Texture Dictionary) class and convenience functions."""

from pathlib import Path

import pytest

from texfury import (
    ITD, Game, Texture, BCFormat,
    create_dict_from_folder, extract_dict,
)


class TestITDConstruction:
    def test_default_game(self):
        td = ITD()
        assert td.game == Game.GTA5
        assert len(td) == 0

    def test_explicit_game(self):
        for game in Game:
            td = ITD(game=game)
            assert td.game == game


class TestITDMutation:
    def test_add(self, png_64):
        td = ITD()
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="added")
        td.add(tex)
        assert len(td) == 1
        assert "added" in td

    def test_add_nameless_raises(self, png_64):
        td = ITD()
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="temp")
        tex.name = ""
        with pytest.raises(ValueError):
            td.add(tex)

    def test_replace(self, png_64, png_128):
        td = ITD()
        tex1 = Texture.from_image(str(png_64), format=BCFormat.BC1, name="body")
        td.add(tex1)

        tex2 = Texture.from_image(str(png_128), format=BCFormat.BC7, name="replacement")
        td.replace("body", tex2)
        assert len(td) == 1
        assert td["body"].format == BCFormat.BC7

    def test_replace_nonexistent_raises(self, png_64):
        td = ITD()
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="x")
        with pytest.raises(KeyError):
            td.replace("nonexistent", tex)

    def test_remove(self, png_64):
        td = ITD()
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="removeme")
        td.add(tex)
        td.remove("removeme")
        assert len(td) == 0
        assert "removeme" not in td

    def test_remove_nonexistent_raises(self):
        td = ITD()
        with pytest.raises(KeyError):
            td.remove("nonexistent")


class TestITDLookup:
    def test_get(self, png_64):
        td = ITD()
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="findme")
        td.add(tex)
        found = td.get("findme")
        assert found.name == "findme"

    def test_get_nonexistent_raises(self):
        td = ITD()
        with pytest.raises(KeyError):
            td.get("nope")

    def test_getitem(self, png_64):
        td = ITD()
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="indexed")
        td.add(tex)
        assert td["indexed"].name == "indexed"

    def test_getitem_nonexistent_raises(self):
        td = ITD()
        with pytest.raises(KeyError):
            _ = td["nope"]

    def test_contains(self, png_64):
        td = ITD()
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="here")
        td.add(tex)
        assert "here" in td
        assert "not_here" not in td

    def test_contains_case_insensitive(self, png_64):
        td = ITD()
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="body_d")
        td.add(tex)
        assert "BODY_D" in td
        assert "Body_D" in td

    def test_names(self, png_64, png_128):
        td = ITD()
        td.add(Texture.from_image(str(png_64), format=BCFormat.BC1, name="a"))
        td.add(Texture.from_image(str(png_128), format=BCFormat.BC1, name="b"))
        assert td.names() == ["a", "b"]


class TestITDIteration:
    def test_iter(self, png_64, png_128):
        td = ITD()
        td.add(Texture.from_image(str(png_64), format=BCFormat.BC1, name="first"))
        td.add(Texture.from_image(str(png_128), format=BCFormat.BC1, name="second"))
        names = [tex.name for tex in td]
        assert names == ["first", "second"]

    def test_len(self, png_64):
        td = ITD()
        assert len(td) == 0
        td.add(Texture.from_image(str(png_64), format=BCFormat.BC1, name="x"))
        assert len(td) == 1


class TestITDRepr:
    def test_repr(self, png_64):
        td = ITD(game=Game.GTA4)
        td.add(Texture.from_image(str(png_64), format=BCFormat.BC1, name="tex1"))
        r = repr(td)
        assert "gta4" in r
        assert "tex1" in r


class TestITDSaveLoad:
    @pytest.mark.parametrize("game,ext", [
        (Game.GTA4, ".wtd"),
        (Game.GTA5, ".ytd"),
        (Game.GTA5_GEN9, ".ytd"),
        (Game.RDR2, ".ytd"),
    ])
    def test_round_trip(self, game, ext, png_64, tmp_path):
        td = ITD(game=game)
        tex = Texture.from_image(str(png_64), format=BCFormat.BC1, name="roundtrip")
        td.add(tex)

        out_path = tmp_path / f"test{ext}"
        td.save(out_path)
        assert out_path.exists()

        td2 = ITD.load(out_path)
        assert td2.game == game
        assert len(td2) == 1
        assert td2["roundtrip"].width == 64
        assert td2["roundtrip"].format == BCFormat.BC1

    @pytest.mark.parametrize("game,ext", [
        (Game.GTA4, ".wtd"),
        (Game.GTA5, ".ytd"),
        (Game.GTA5_GEN9, ".ytd"),
        (Game.RDR2, ".ytd"),
    ])
    def test_multi_texture_round_trip(self, game, ext, image_folder, tmp_path):
        td = ITD.from_folder(image_folder, game=game, format=BCFormat.BC1)
        assert len(td) == 3

        out_path = tmp_path / f"multi{ext}"
        td.save(out_path)

        td2 = ITD.load(out_path)
        assert td2.game == game
        assert len(td2) == 3
        assert sorted(td2.names()) == sorted(td.names())


class TestITDFromFolder:
    def test_basic(self, image_folder):
        td = ITD.from_folder(image_folder, format=BCFormat.BC1)
        assert isinstance(td, ITD)
        assert td.game == Game.GTA5
        assert len(td) == 3
        assert sorted(td.names()) == ["blue", "green", "red"]

    def test_with_game(self, image_folder):
        td = ITD.from_folder(image_folder, game=Game.RDR2, format=BCFormat.BC1)
        assert td.game == Game.RDR2

    def test_empty_folder_raises(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError):
            ITD.from_folder(empty)

    def test_nonexistent_folder_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ITD.from_folder(tmp_path / "nope")

    def test_progress_callback(self, image_folder):
        calls = []
        td = ITD.from_folder(
            image_folder, format=BCFormat.BC1,
            on_progress=lambda i, total, name: calls.append((i, total, name)),
        )
        assert len(calls) == 3
        assert all(total == 3 for _, total, _ in calls)


class TestITDExtract:
    def test_extract(self, image_folder, tmp_path):
        td = ITD.from_folder(image_folder, format=BCFormat.BC1)
        out = td.extract(tmp_path / "extracted")
        dds_files = sorted(out.glob("*.dds"))
        assert len(dds_files) == 3

        # Verify DDS files are loadable
        for dds in dds_files:
            tex = Texture.from_dds(str(dds))
            assert tex.width > 0


class TestITDInspect:
    @pytest.mark.parametrize("game,ext", [
        (Game.GTA4, ".wtd"),
        (Game.GTA5, ".ytd"),
        (Game.GTA5_GEN9, ".ytd"),
        (Game.RDR2, ".ytd"),
    ])
    def test_inspect(self, game, ext, png_64, tmp_path):
        td = ITD(game=game)
        td.add(Texture.from_image(str(png_64), format=BCFormat.BC1, name="inspected"))
        out_path = tmp_path / f"inspect{ext}"
        td.save(out_path)

        info = ITD.inspect(out_path)
        assert len(info) == 1
        entry = info[0]
        assert entry["name"] == "inspected"
        assert entry["width"] == 64
        assert entry["height"] == 64
        assert "format_name" in entry
        assert "mip_count" in entry
        assert "data_size" in entry


class TestGTA4Restrictions:
    @pytest.mark.parametrize("fmt", [BCFormat.BC4, BCFormat.BC5, BCFormat.BC7])
    def test_unsupported_formats_rejected(self, fmt, png_64, tmp_path):
        td = ITD(game=Game.GTA4)
        tex = Texture.from_image(str(png_64), format=fmt, name="test")
        td.add(tex)
        with pytest.raises((ValueError, KeyError)):
            td.save(tmp_path / "fail.wtd")

    @pytest.mark.parametrize("fmt", [BCFormat.BC1, BCFormat.BC3, BCFormat.A8R8G8B8])
    def test_supported_formats_accepted(self, fmt, png_64, tmp_path):
        td = ITD(game=Game.GTA4)
        tex = Texture.from_image(str(png_64), format=fmt, name="test")
        td.add(tex)
        out = tmp_path / f"ok_{fmt.name}.wtd"
        td.save(out)
        assert out.exists()


class TestCreateDictFromFolder:
    def test_returns_itd(self, image_folder, tmp_path):
        td = create_dict_from_folder(image_folder, tmp_path / "test.ytd")
        assert isinstance(td, ITD)
        assert len(td) == 3

    def test_saves_when_output_given(self, image_folder, tmp_path):
        out = tmp_path / "saved.ytd"
        create_dict_from_folder(image_folder, out, format=BCFormat.BC1)
        assert out.exists()

    def test_no_save_when_output_none(self, image_folder, tmp_path):
        td = create_dict_from_folder(image_folder, format=BCFormat.BC1)
        assert isinstance(td, ITD)
        assert len(td) == 3
        # No file should have been written to tmp_path
        ytd_files = list(tmp_path.glob("*.ytd"))
        assert len(ytd_files) == 0


class TestExtractDict:
    def test_from_path(self, image_folder, tmp_path):
        ytd_path = tmp_path / "source.ytd"
        create_dict_from_folder(image_folder, ytd_path, format=BCFormat.BC1)

        out = extract_dict(ytd_path, tmp_path / "out")
        assert len(list(out.glob("*.dds"))) == 3

    def test_from_itd(self, image_folder, tmp_path):
        td = ITD.from_folder(image_folder, format=BCFormat.BC1)
        out = extract_dict(td, tmp_path / "from_itd")
        assert len(list(out.glob("*.dds"))) == 3

    def test_default_output_from_path(self, image_folder, tmp_path):
        ytd_path = tmp_path / "mydict.ytd"
        create_dict_from_folder(image_folder, ytd_path, format=BCFormat.BC1)

        out = extract_dict(ytd_path)
        assert out == tmp_path / "mydict"
        assert len(list(out.glob("*.dds"))) == 3
