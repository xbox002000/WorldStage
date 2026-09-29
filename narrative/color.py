"""Deterministic avatar colours that always read well under white text, whatever the hue."""
from __future__ import annotations

import colorsys
import hashlib

MAX_LUMINANCE = 0.19  # white on this is at least ~4.2:1, even a little washed out by weather or night tint
SATURATION = 55


def luminance(hsl: str) -> float:
    """WCAG relative luminance of an `hsl(h, s%, l%)` colour."""
    h, s, l = [float(v.strip(" %)")) for v in hsl[hsl.index("(") + 1:].split(",")]
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


GOLDEN_ANGLE = 137.508  # successive hues land as far from all earlier ones as possible


def avatar_color(person_id: str, slot: int | None = None) -> str:
    """A stable colour per person, lightness lowered until white text reads.

    With a `slot` (the person's place in the world's cast) hues are spread evenly by the golden angle, so no two
    people look alike. Without one, the hue comes from a digest of the id.
    """
    if slot is not None:
        hue = round(slot * GOLDEN_ANGLE) % 360
    else:
        hue = int(hashlib.md5(person_id.encode()).hexdigest()[:6], 16) % 360  # a stable digest, not security
    for lightness in range(46, 18, -2):
        color = f"hsl({hue}, {SATURATION}%, {lightness}%)"
        if luminance(color) <= MAX_LUMINANCE:
            return color
    return f"hsl({hue}, {SATURATION}%, 18%)"


def ink_for(hsl: str) -> str:
    """Whichever of white and near-black reads better on this colour (older packets used lighter fills)."""
    lum = luminance(hsl)
    white = 1.05 / (lum + 0.05)  # WCAG contrast ratio of white (L = 1) on this colour
    dark = (lum + 0.05) / (0.006 + 0.05)  # ... and of #0d1117 (L ~ 0.006)
    return "#ffffff" if white >= dark else "#0d1117"
