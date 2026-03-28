"""Test RSC resource format modules."""

from texfury.rsc import (
    DAT_VIRTUAL_BASE, DAT_PHYSICAL_BASE, DAT_BASE_SIZE,
    RSC5_MAGIC, build_rsc5, decompress_rsc5,
    RSC7_MAGIC, build_rsc7, decompress_rsc7,
    RSC8_MAGIC, build_rsc8, decompress_rsc8,
)


class TestRSCConstants:
    def test_base_addresses(self):
        assert DAT_VIRTUAL_BASE == 0x50000000
        assert DAT_PHYSICAL_BASE == 0x60000000

    def test_base_size(self):
        assert DAT_BASE_SIZE == 0x2000

    def test_magic_values(self):
        assert RSC5_MAGIC == 0x05435352
        assert RSC7_MAGIC == 0x37435352
        assert RSC8_MAGIC == 0x38435352


class TestRSC5:
    def test_round_trip(self):
        vdata = b"\xAA" * 256
        pdata = b"\xBB" * 128
        packed = build_rsc5(vdata, pdata)
        v_out, p_out = decompress_rsc5(packed)
        assert v_out[:len(vdata)] == vdata
        assert p_out[:len(pdata)] == pdata

    def test_empty_physical(self):
        vdata = b"\xCC" * 64
        packed = build_rsc5(vdata, b"")
        v_out, p_out = decompress_rsc5(packed)
        assert v_out[:len(vdata)] == vdata


class TestRSC7:
    def test_round_trip(self):
        vdata = b"\xDD" * 1024
        pdata = b"\xEE" * 2048
        packed = build_rsc7(vdata, pdata)
        v_out, p_out = decompress_rsc7(packed)
        assert v_out[:len(vdata)] == vdata
        assert p_out[:len(pdata)] == pdata


class TestRSC8:
    def test_round_trip(self):
        vdata = b"\x11" * 512
        pdata = b"\x22" * 1024
        packed = build_rsc8(vdata, pdata)
        v_out, p_out = decompress_rsc8(packed)
        assert v_out[:len(vdata)] == vdata
        assert p_out[:len(pdata)] == pdata
