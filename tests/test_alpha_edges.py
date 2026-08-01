from __future__ import annotations

from texfury import BCFormat, Texture


def _foliage_rgba(*, padded: bool) -> bytes:
    pixels = bytearray()
    for y in range(16):
        for x in range(16):
            inside = 4 <= x < 12 and 4 <= y < 12
            partial = (
                3 <= x < 13
                and 3 <= y < 13
                and not inside
            )
            if inside:
                pixels.extend((32, 180, 48, 255))
            elif partial:
                color = (32, 180, 48) if padded else (0, 0, 0)
                pixels.extend((*color, 64))
            else:
                color = (32, 180, 48) if padded else (0, 0, 0)
                pixels.extend((*color, 0))
    return bytes(pixels)


def _raw_texture(data: bytes) -> Texture:
    return Texture.from_raw(
        data,
        16,
        16,
        BCFormat.R8G8B8A8,
        1,
        [0],
        [len(data)],
        name="foliage",
    )


def test_detects_black_matted_partial_alpha() -> None:
    report = _raw_texture(_foliage_rgba(padded=False)).inspect_alpha_edges()

    assert report.needs_pixel_repair
    assert report.suspicious_levels == (0,)
    assert report.levels[0].dark_low_alpha_fraction == 1.0


def test_clean_edge_padding_is_lossless_noop() -> None:
    texture = _raw_texture(_foliage_rgba(padded=True))

    assert not texture.inspect_alpha_edges().needs_pixel_repair
    assert texture.repair_alpha_edges() is texture


def test_repair_changes_rgb_but_preserves_alpha() -> None:
    texture = _raw_texture(_foliage_rgba(padded=False))
    before, _, _ = texture.to_rgba()

    repaired = texture.repair_alpha_edges(radius=4)
    after, _, _ = repaired.to_rgba()

    assert repaired is not texture
    assert repaired.data != texture.data
    assert after[3::4] == before[3::4]
    assert not repaired.inspect_alpha_edges().needs_pixel_repair


def test_bc3_repair_preserves_encoded_alpha_chain() -> None:
    texture = _raw_texture(_foliage_rgba(padded=False)).to_format(
        BCFormat.BC3,
        generate_mipmaps=False,
        quality=1.0,
    )
    before, _, _ = texture.to_rgba()

    repaired = texture.repair_alpha_edges(radius=4)
    after, _, _ = repaired.to_rgba()

    assert repaired.data != texture.data
    assert after[3::4] == before[3::4]
    assert not repaired.inspect_alpha_edges().needs_pixel_repair
