"""Shared color conversion utilities.

Internal module for cross-output-format color math (ANSI writer, HTML renderer, etc.).
"""

from __future__ import annotations

_CUBE_START = 16
_GRAY_START = 232

_BASIC_RGB: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),  # 0: black
    (128, 0, 0),  # 1: red
    (0, 128, 0),  # 2: green
    (128, 128, 0),  # 3: yellow
    (0, 0, 128),  # 4: blue
    (128, 0, 128),  # 5: magenta
    (0, 128, 128),  # 6: cyan
    (192, 192, 192),  # 7: white
    (128, 128, 128),  # 8: bright black (gray)
    (255, 0, 0),  # 9: bright red
    (0, 255, 0),  # 10: bright green
    (255, 255, 0),  # 11: bright yellow
    (0, 0, 255),  # 12: bright blue
    (255, 0, 255),  # 13: bright magenta
    (0, 255, 255),  # 14: bright cyan
    (255, 255, 255),  # 15: bright white
)


def _color_distance_sq(r1: int, g1: int, b1: int, r2: int, g2: int, b2: int) -> int:
    """Squared Euclidean distance in RGB space."""
    return (r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2


def _idx_to_rgb(idx: int) -> tuple[int, int, int]:
    """Convert a 256-color index to approximate RGB."""
    if idx < 16:
        return _BASIC_RGB[idx]
    if idx < _GRAY_START:
        idx -= _CUBE_START
        b = (idx % 6) * 51
        idx //= 6
        g = (idx % 6) * 51
        r = (idx // 6) * 51
        return (r, g, b)
    gray = 8 + (idx - _GRAY_START) * 10
    return (gray, gray, gray)


def _rgb_to_256(r: int, g: int, b: int) -> int:
    """Find nearest 256-color index for an RGB value."""
    best_idx = 16
    best_dist = _color_distance_sq(r, g, b, *_idx_to_rgb(16))
    for i in range(17, 256):
        ir, ig, ib = _idx_to_rgb(i)
        d = _color_distance_sq(r, g, b, ir, ig, ib)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def _rgb_to_basic(r: int, g: int, b: int) -> int:
    """Find nearest basic 16-color index for an RGB value."""
    best_idx = 0
    best_dist = _color_distance_sq(r, g, b, *_BASIC_RGB[0])
    for i in range(1, 16):
        d = _color_distance_sq(r, g, b, *_BASIC_RGB[i])
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def _nearest_basic(idx_256: int) -> int:
    """Convert a 256-color index to the nearest basic 16-color index."""
    r, g, b = _idx_to_rgb(idx_256)
    return _rgb_to_basic(r, g, b)
