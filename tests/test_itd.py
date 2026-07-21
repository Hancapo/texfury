"""Test ITD (Internal Texture Dictionary) class and convenience functions."""

from pathlib import Path

import pytest

from texfury import (
    ITD, Game, Texture, BCFormat,
    create_dict_from_folder, extract_dict,
)
from texfury.rsc import DAT_PHYSICAL_BASE, DAT_VIRTUAL_BASE, build_rsc7


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

    @pytest.mark.parametrize("name", [
        "../escaped",
        r"..\escaped",
    ])
    def test_rejects_path_traversal(self, png_64, tmp_path, name):
        td = ITD()
        td.add(Texture.from_image(
            png_64, format=BCFormat.BC1, name="valid_before_unsafe"))
        td.add(Texture.from_image(png_64, format=BCFormat.BC1, name=name))
        output = tmp_path / "extracted"

        with pytest.raises(ValueError, match="Unsafe texture name"):
            td.extract(output)

        assert not (tmp_path / "escaped.dds").exists()
        assert not (output / "valid_before_unsafe.dds").exists()


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


def _build_minimal_ps3_ctd() -> bytes:
    virtual = bytearray(0x100)
    physical = bytes.fromhex("00 f8 00 f8 00 00 00 00")

    # PS3 pgDictionary root.
    virtual[0x00:0x04] = (0xE0678100).to_bytes(4, "big")
    virtual[0x04:0x08] = (DAT_VIRTUAL_BASE + 0x70).to_bytes(4, "big")
    virtual[0x0C:0x10] = (1).to_bytes(4, "big")
    virtual[0x10:0x14] = (DAT_VIRTUAL_BASE + 0x80).to_bytes(4, "big")
    virtual[0x14:0x18] = (0x00010001).to_bytes(4, "big")
    virtual[0x18:0x1C] = (DAT_VIRTUAL_BASE + 0x90).to_bytes(4, "big")
    virtual[0x1C:0x20] = (0x00010001).to_bytes(4, "big")

    # grcTextureGCM object at 0x20, with CellGcmTexture at +0x08.
    tex = 0x20
    virtual[tex + 0x00:tex + 0x04] = (0xFC588A00).to_bytes(4, "big")
    virtual[tex + 0x08:tex + 0x0C] = bytes([0x86, 1, 2, 0])  # DXT1, 1 mip, 2D
    virtual[tex + 0x0C:tex + 0x10] = (0x0000A9E4).to_bytes(4, "big")
    virtual[tex + 0x10:tex + 0x12] = (4).to_bytes(2, "big")
    virtual[tex + 0x12:tex + 0x14] = (4).to_bytes(2, "big")
    virtual[tex + 0x14:tex + 0x16] = (1).to_bytes(2, "big")
    virtual[tex + 0x1C:tex + 0x20] = DAT_PHYSICAL_BASE.to_bytes(4, "big")
    virtual[tex + 0x20:tex + 0x24] = (DAT_VIRTUAL_BASE + 0xA0).to_bytes(4, "big")
    virtual[tex + 0x24:tex + 0x28] = (0x00018000).to_bytes(4, "big")
    virtual[tex + 0x28:tex + 0x2C] = (DAT_VIRTUAL_BASE + tex + 0x08).to_bytes(4, "big")
    virtual[tex + 0x2C:tex + 0x30] = (0x20000008).to_bytes(4, "big")
    virtual[tex + 0x34:tex + 0x38] = (DAT_VIRTUAL_BASE + 0x60).to_bytes(4, "big")

    virtual[0x60:0x64] = (0).to_bytes(4, "big")
    virtual[0x80:0x84] = (0x12345678).to_bytes(4, "big")
    virtual[0x90:0x94] = (DAT_VIRTUAL_BASE + tex).to_bytes(4, "big")
    virtual[0xA0:0xA9] = b"ps3_test\x00"

    return build_rsc7(bytes(virtual), physical)


class TestGTA5PS3CTD:
    def test_load_ctd(self, tmp_path):
        path = tmp_path / "fixture.ctd"
        path.write_bytes(_build_minimal_ps3_ctd())

        td = ITD.load(path)

        assert td.game == Game.GTA5_PS3
        assert len(td) == 1
        tex = td["ps3_test"]
        assert tex.width == 4
        assert tex.height == 4
        assert tex.format == BCFormat.BC1
        assert tex.mip_count == 1
        assert tex.data == bytes.fromhex("00 f8 00 f8 00 00 00 00")

    def test_inspect_ctd(self, tmp_path):
        path = tmp_path / "fixture.ctd"
        path.write_bytes(_build_minimal_ps3_ctd())

        info = ITD.inspect(path)

        assert info == [{
            "name": "ps3_test",
            "width": 4,
            "height": 4,
            "format": BCFormat.BC1,
            "format_name": "BC1",
            "mip_count": 1,
            "data_size": 8,
            "gcm_format": 0x86,
        }]

    def test_save_ctd_is_read_only(self):
        td = ITD(game=Game.GTA5_PS3)
        with pytest.raises(NotImplementedError):
            td.save("unsupported.ctd")


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
