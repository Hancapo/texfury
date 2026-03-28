"""Integration tests using vanilla YTD files.

Tests are skipped if the fixture file is not present.
"""

from pathlib import Path

import pytest

from texfury import ITD, Game, Texture, BCFormat

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ── GTA V Legacy ────────────────────────────────────────────────────────────


@pytest.fixture
def legacy_ytd():
    p = FIXTURES / "legacy.ytd"
    if not p.exists():
        pytest.skip("legacy.ytd not present")
    return ITD.load(p)


class TestLegacyYTDLoad:
    def test_game(self, legacy_ytd):
        assert legacy_ytd.game == Game.GTA5

    def test_texture_count(self, legacy_ytd):
        assert len(legacy_ytd) == 9

    def test_all_textures_valid(self, legacy_ytd):
        for tex in legacy_ytd:
            assert tex.width > 0
            assert tex.height > 0
            assert tex.mip_count >= 1
            assert len(tex.data) > 0
            assert tex.name

    def test_getitem(self, legacy_ytd):
        name = legacy_ytd.names()[0]
        assert legacy_ytd[name].name == name

    def test_contains(self, legacy_ytd):
        assert legacy_ytd.names()[0] in legacy_ytd
        assert "nonexistent_xyz" not in legacy_ytd


class TestLegacyYTDRoundTrip:
    def test_save_reload(self, legacy_ytd, tmp_path):
        out = tmp_path / "legacy_rt.ytd"
        legacy_ytd.save(out)

        td2 = ITD.load(out)
        assert td2.game == Game.GTA5
        assert len(td2) == len(legacy_ytd)
        assert legacy_ytd.names() == td2.names()

        for t1, t2 in zip(legacy_ytd, td2):
            assert t1.name == t2.name
            assert t1.width == t2.width
            assert t1.height == t2.height
            assert t1.format == t2.format
            assert t1.mip_count == t2.mip_count
            assert len(t1.data) == len(t2.data)


class TestLegacyYTDInspect:
    def test_inspect(self):
        p = FIXTURES / "legacy.ytd"
        if not p.exists():
            pytest.skip("legacy.ytd not present")
        info = ITD.inspect(p)
        assert len(info) == 9
        for entry in info:
            assert "name" in entry
            assert "width" in entry
            assert "height" in entry
            assert "format_name" in entry
            assert "mip_count" in entry
            assert "data_size" in entry


class TestLegacyYTDExtract:
    def test_extract_all(self, legacy_ytd, tmp_path):
        out = legacy_ytd.extract(tmp_path / "extracted")
        dds_files = sorted(out.glob("*.dds"))
        assert len(dds_files) == 9
        for dds in dds_files:
            tex = Texture.from_dds(str(dds))
            assert tex.width > 0


class TestLegacyYTDDecompress:
    def test_decompress_all(self, legacy_ytd):
        for tex in legacy_ytd:
            rgba, w, h = tex.to_rgba()
            assert w == tex.width
            assert h == tex.height
            assert len(rgba) == w * h * 4


# ── GTA V Enhanced (gen9) ───────────────────────────────────────────────────


@pytest.fixture
def enhanced_ytd():
    p = FIXTURES / "enhanced.ytd"
    if not p.exists():
        pytest.skip("enhanced.ytd not present")
    return ITD.load(p)


class TestEnhancedYTDLoad:
    def test_game(self, enhanced_ytd):
        assert enhanced_ytd.game == Game.GTA5_GEN9

    def test_texture_count(self, enhanced_ytd):
        assert len(enhanced_ytd) == 17

    def test_all_textures_valid(self, enhanced_ytd):
        for tex in enhanced_ytd:
            assert tex.width > 0
            assert tex.height > 0
            assert tex.mip_count >= 1
            assert len(tex.data) > 0
            assert tex.name

    def test_getitem(self, enhanced_ytd):
        name = enhanced_ytd.names()[0]
        assert enhanced_ytd[name].name == name

    def test_contains(self, enhanced_ytd):
        assert enhanced_ytd.names()[0] in enhanced_ytd
        assert "nonexistent_xyz" not in enhanced_ytd


class TestEnhancedYTDRoundTrip:
    def test_save_reload(self, enhanced_ytd, tmp_path):
        out = tmp_path / "enhanced_rt.ytd"
        enhanced_ytd.save(out)

        td2 = ITD.load(out)
        assert td2.game == Game.GTA5_GEN9
        assert len(td2) == len(enhanced_ytd)
        assert enhanced_ytd.names() == td2.names()

        for t1, t2 in zip(enhanced_ytd, td2):
            assert t1.name == t2.name
            assert t1.width == t2.width
            assert t1.height == t2.height
            assert t1.format == t2.format
            assert t1.mip_count == t2.mip_count
            assert len(t1.data) == len(t2.data)


class TestEnhancedYTDInspect:
    def test_inspect(self):
        p = FIXTURES / "enhanced.ytd"
        if not p.exists():
            pytest.skip("enhanced.ytd not present")
        info = ITD.inspect(p)
        assert len(info) == 17
        for entry in info:
            assert "name" in entry
            assert "width" in entry
            assert "height" in entry
            assert "format_name" in entry
            assert "mip_count" in entry
            assert "data_size" in entry


class TestEnhancedYTDExtract:
    def test_extract_all(self, enhanced_ytd, tmp_path):
        out = enhanced_ytd.extract(tmp_path / "extracted")
        dds_files = sorted(out.glob("*.dds"))
        assert len(dds_files) == 17
        for dds in dds_files:
            tex = Texture.from_dds(str(dds))
            assert tex.width > 0


class TestEnhancedYTDDecompress:
    def test_decompress_all(self, enhanced_ytd):
        for tex in enhanced_ytd:
            rgba, w, h = tex.to_rgba()
            assert w == tex.width
            assert h == tex.height
            assert len(rgba) == w * h * 4


# ── RDR2 ────────────────────────────────────────────────────────────────────


@pytest.fixture
def rdr2_ytd():
    p = FIXTURES / "rdr2.ytd"
    if not p.exists():
        pytest.skip("rdr2.ytd not present")
    return ITD.load(p)


class TestRDR2YTDLoad:
    def test_game(self, rdr2_ytd):
        assert rdr2_ytd.game == Game.RDR2

    def test_texture_count(self, rdr2_ytd):
        assert len(rdr2_ytd) == 29

    def test_all_textures_valid(self, rdr2_ytd):
        for tex in rdr2_ytd:
            assert tex.width > 0
            assert tex.height > 0
            assert tex.mip_count >= 1
            assert len(tex.data) > 0
            assert tex.name

    def test_getitem(self, rdr2_ytd):
        name = rdr2_ytd.names()[0]
        assert rdr2_ytd[name].name == name

    def test_contains(self, rdr2_ytd):
        assert rdr2_ytd.names()[0] in rdr2_ytd
        assert "nonexistent_xyz" not in rdr2_ytd


class TestRDR2YTDRoundTrip:
    def test_save_reload(self, rdr2_ytd, tmp_path):
        out = tmp_path / "rdr2_rt.ytd"
        rdr2_ytd.save(out)

        td2 = ITD.load(out)
        assert td2.game == Game.RDR2
        assert len(td2) == len(rdr2_ytd)
        assert rdr2_ytd.names() == td2.names()

        for t1, t2 in zip(rdr2_ytd, td2):
            assert t1.name == t2.name
            assert t1.width == t2.width
            assert t1.height == t2.height
            assert t1.format == t2.format
            assert t1.mip_count == t2.mip_count
            assert len(t1.data) == len(t2.data)


class TestRDR2YTDInspect:
    def test_inspect(self):
        p = FIXTURES / "rdr2.ytd"
        if not p.exists():
            pytest.skip("rdr2.ytd not present")
        info = ITD.inspect(p)
        assert len(info) == 29
        for entry in info:
            assert "name" in entry
            assert "width" in entry
            assert "height" in entry
            assert "format_name" in entry
            assert "mip_count" in entry
            assert "data_size" in entry


class TestRDR2YTDExtract:
    def test_extract_all(self, rdr2_ytd, tmp_path):
        out = rdr2_ytd.extract(tmp_path / "extracted")
        dds_files = sorted(out.glob("*.dds"))
        assert len(dds_files) == 29
        for dds in dds_files:
            tex = Texture.from_dds(str(dds))
            assert tex.width > 0


class TestRDR2YTDDecompress:
    def test_decompress_sample(self, rdr2_ytd):
        """Decompress a few textures (not all — some are large)."""
        for tex in list(rdr2_ytd)[:5]:
            rgba, w, h = tex.to_rgba()
            assert w == tex.width
            assert h == tex.height
            assert len(rgba) == w * h * 4
