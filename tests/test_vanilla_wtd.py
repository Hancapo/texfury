"""Integration tests using vanilla GTA IV WTD file.

These tests are skipped if nj04e_glue.wtd is not present (e.g. in CI).
"""

import pytest

from texfury import ITD, Game, Texture, BCFormat


pytestmark = pytest.mark.skipif(
    not pytest.importorskip("pathlib").Path(
        __file__
    ).resolve().parent.parent.joinpath("nj04e_glue.wtd").exists(),
    reason="nj04e_glue.wtd not present",
)


@pytest.fixture
def wtd():
    return ITD.load("nj04e_glue.wtd")


class TestVanillaWTDLoad:
    def test_game(self, wtd):
        assert wtd.game == Game.GTA4

    def test_texture_count(self, wtd):
        assert len(wtd) == 29

    def test_all_textures_valid(self, wtd):
        for tex in wtd:
            assert tex.width > 0
            assert tex.height > 0
            assert tex.mip_count >= 1
            assert len(tex.data) > 0
            assert tex.name
            assert tex.format in (BCFormat.BC1, BCFormat.BC3, BCFormat.A8R8G8B8)

    def test_iteration(self, wtd):
        count = sum(1 for _ in wtd)
        assert count == 29

    def test_getitem(self, wtd):
        name = wtd.names()[0]
        assert wtd[name].name == name

    def test_contains(self, wtd):
        assert wtd.names()[0] in wtd
        assert "this_does_not_exist_xyz" not in wtd


class TestVanillaWTDRoundTrip:
    def test_save_reload(self, wtd, tmp_path):
        out = tmp_path / "roundtrip.wtd"
        wtd.save(out)

        wtd2 = ITD.load(out)
        assert wtd2.game == Game.GTA4
        assert len(wtd2) == 29
        assert wtd.names() == wtd2.names()

        for t1, t2 in zip(wtd, wtd2):
            assert t1.name == t2.name
            assert t1.width == t2.width
            assert t1.height == t2.height
            assert t1.format == t2.format
            assert t1.mip_count == t2.mip_count
            assert len(t1.data) == len(t2.data)


class TestVanillaWTDInspect:
    def test_inspect(self):
        info = ITD.inspect("nj04e_glue.wtd")
        assert len(info) == 29
        for entry in info:
            assert "name" in entry
            assert "width" in entry
            assert "height" in entry
            assert "format_name" in entry
            assert "mip_count" in entry
            assert "data_size" in entry


class TestVanillaWTDExtract:
    def test_extract_all(self, wtd, tmp_path):
        out = wtd.extract(tmp_path / "extracted")
        dds_files = sorted(out.glob("*.dds"))
        assert len(dds_files) == 29

        for dds in dds_files:
            tex = Texture.from_dds(str(dds))
            assert tex.width > 0


class TestVanillaWTDDecompress:
    def test_decompress_all(self, wtd):
        for tex in list(wtd)[:5]:
            rgba, w, h = tex.to_rgba()
            assert w == tex.width
            assert h == tex.height
            assert len(rgba) == w * h * 4
