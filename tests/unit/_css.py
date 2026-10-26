"""Colour maths shared by the stylesheet contrast tests (audit F-274).

Three test modules each carried their own copy of these, and a fix to one
would not have reached the others.
"""

from __future__ import annotations


def luminance(colour: str) -> float:
    """WCAG relative luminance of a ``#RRGGBB`` colour."""
    raw = colour.lstrip("#")
    channels = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two ``#RRGGBB`` colours."""
    a, b = luminance(foreground), luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def over(foreground: str, alpha: float, background: str) -> str:
    """*foreground* at *alpha* composited onto *background*."""
    f = [int(foreground.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    mixed = [round(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3)]
    return "#{:02X}{:02X}{:02X}".format(*mixed)
