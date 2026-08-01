"""Alpha-edge diagnostics and pixel repair primitives."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlphaEdgeMipReport:
    level: int
    width: int
    height: int
    transparent_boundary_pixels: int
    dark_transparent_boundary_pixels: int
    low_alpha_boundary_pixels: int
    dark_low_alpha_boundary_pixels: int

    @property
    def dark_transparent_fraction(self) -> float:
        if not self.transparent_boundary_pixels:
            return 0.0
        return (
            self.dark_transparent_boundary_pixels
            / self.transparent_boundary_pixels
        )

    @property
    def dark_low_alpha_fraction(self) -> float:
        if not self.low_alpha_boundary_pixels:
            return 0.0
        return self.dark_low_alpha_boundary_pixels / self.low_alpha_boundary_pixels

    @property
    def is_suspicious(self) -> bool:
        return (
            self.transparent_boundary_pixels >= 8
            and self.dark_transparent_fraction >= 0.5
        ) or (
            self.low_alpha_boundary_pixels >= 8
            and self.dark_low_alpha_fraction >= 0.5
        )


@dataclass(frozen=True, slots=True)
class AlphaEdgeReport:
    levels: tuple[AlphaEdgeMipReport, ...]

    @property
    def suspicious_levels(self) -> tuple[int, ...]:
        return tuple(level.level for level in self.levels if level.is_suspicious)

    @property
    def needs_pixel_repair(self) -> bool:
        return bool(self.suspicious_levels)


def _luminance(red: int, green: int, blue: int) -> int:
    return (54 * red + 183 * green + 19 * blue) // 256


def inspect_alpha_mip(
    rgba: bytes,
    width: int,
    height: int,
    level: int,
    *,
    dark_luminance: int = 8,
    low_alpha_limit: int = 64,
    opaque_alpha: int = 240,
    dark_ratio: float = 0.7,
) -> AlphaEdgeMipReport:
    transparent_boundary = 0
    dark_transparent_boundary = 0
    low_alpha_boundary = 0
    dark_low_alpha_boundary = 0

    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 4
            red, green, blue, alpha = rgba[offset : offset + 4]
            opaque_luminances: list[int] = []
            has_visible_neighbor = False
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx = x + dx
                ny = y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                neighbor = (ny * width + nx) * 4
                nr, ng, nb, na = rgba[neighbor : neighbor + 4]
                if na >= 128:
                    has_visible_neighbor = True
                if na >= opaque_alpha:
                    opaque_luminances.append(_luminance(nr, ng, nb))

            luminance = _luminance(red, green, blue)
            if alpha == 0 and has_visible_neighbor:
                transparent_boundary += 1
                if luminance <= dark_luminance:
                    dark_transparent_boundary += 1
            elif 0 < alpha <= low_alpha_limit and opaque_luminances:
                low_alpha_boundary += 1
                reference = sum(opaque_luminances) / len(opaque_luminances)
                if reference > 0 and luminance < reference * dark_ratio:
                    dark_low_alpha_boundary += 1

    return AlphaEdgeMipReport(
        level,
        width,
        height,
        transparent_boundary,
        dark_transparent_boundary,
        low_alpha_boundary,
        dark_low_alpha_boundary,
    )


def repair_alpha_mip(
    rgba: bytes,
    width: int,
    height: int,
    *,
    radius: int = 4,
    opaque_alpha: int = 240,
    partial_alpha_limit: int = 192,
    dark_ratio: float = 0.75,
) -> tuple[bytes, int]:
    if radius < 1:
        raise ValueError("alpha edge repair radius must be positive")
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA data size does not match its dimensions")

    pixel_count = width * height
    distance = bytearray([255]) * pixel_count
    nearest_rgb = bytearray(pixel_count * 3)
    pending: deque[int] = deque()

    for index in range(pixel_count):
        offset = index * 4
        if rgba[offset + 3] < opaque_alpha:
            continue
        distance[index] = 0
        nearest_rgb[index * 3 : index * 3 + 3] = rgba[offset : offset + 3]
        pending.append(index)

    while pending:
        index = pending.popleft()
        next_distance = distance[index] + 1
        if next_distance > radius:
            continue
        x = index % width
        y = index // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            neighbor = ny * width + nx
            if distance[neighbor] != 255:
                continue
            distance[neighbor] = next_distance
            nearest_rgb[neighbor * 3 : neighbor * 3 + 3] = nearest_rgb[
                index * 3 : index * 3 + 3
            ]
            pending.append(neighbor)

    repaired = bytearray(rgba)
    changed = 0
    for index in range(pixel_count):
        offset = index * 4
        alpha = rgba[offset + 3]
        if alpha >= opaque_alpha or distance[index] == 255:
            continue
        source = nearest_rgb[index * 3 : index * 3 + 3]
        replace = alpha == 0
        if 0 < alpha <= partial_alpha_limit:
            current_luminance = _luminance(*rgba[offset : offset + 3])
            source_luminance = _luminance(*source)
            replace = (
                source_luminance > 0
                and current_luminance < source_luminance * dark_ratio
            )
        if replace and repaired[offset : offset + 3] != source:
            repaired[offset : offset + 3] = source
            changed += 1

    return bytes(repaired), changed


__all__ = [
    "AlphaEdgeMipReport",
    "AlphaEdgeReport",
    "inspect_alpha_mip",
    "repair_alpha_mip",
]
