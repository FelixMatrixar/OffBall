"""Colour checks for kits: OKLab distance under simulated colour-vision deficiency (PRD 12.3, 16.3)."""

from __future__ import annotations

import numpy as np

# Machado, Oliveira and Fernandes (2009), severity 1.0, applied to linear RGB.
CVD_MATRICES: dict[str, np.ndarray] = {
    "protanopia": np.array(
        [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]
    ),
    "deuteranopia": np.array(
        [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]
    ),
    "tritanopia": np.array(
        [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]
    ),
}
PITCH_GREEN = "#2e6b3a"
KIT_MIN_DELTA = 0.12
PITCH_MIN_DELTA = 0.07


def hex_to_rgb(hex_colour: str) -> np.ndarray:
    h = hex_colour.lstrip("#")
    return np.array([int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)])


def rgb_to_hex(rgb: np.ndarray) -> str:
    c = np.clip(np.round(rgb * 255), 0, 255).astype(int)
    return "#{:02x}{:02x}{:02x}".format(*c)


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_oklab(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb
    lms = np.array(
        [
            0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
            0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
            0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b,
        ]
    )
    l_, m_, s_ = np.cbrt(lms)
    return np.array(
        [
            0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
        ]
    )


def oklab(hex_colour: str, vision: str = "normal") -> np.ndarray:
    lin = srgb_to_linear(hex_to_rgb(hex_colour))
    if vision != "normal":
        lin = np.clip(CVD_MATRICES[vision] @ lin, 0.0, 1.0)
    return linear_to_oklab(lin)


def delta(a: str, b: str, vision: str = "normal") -> float:
    return float(np.linalg.norm(oklab(a, vision) - oklab(b, vision)))


VISIONS = ("normal", "protanopia", "deuteranopia", "tritanopia")


def min_delta(a: str, b: str) -> float:
    """The smallest OKLab distance between two colours across normal vision and three CVD simulations."""
    return min(delta(a, b, v) for v in VISIONS)


def kits_distinguishable(a: str, b: str) -> bool:
    return (
        min_delta(a, b) >= KIT_MIN_DELTA
        and min_delta(a, PITCH_GREEN) >= PITCH_MIN_DELTA
        and min_delta(b, PITCH_GREEN) >= PITCH_MIN_DELTA
    )


def oklch_to_hex(lightness: float, chroma: float, hue_deg: float) -> str:
    """OKLCh to sRGB hex, clipping out-of-gamut colours."""
    h = np.radians(hue_deg)
    lab = np.array([lightness, chroma * np.cos(h), chroma * np.sin(h)])
    l_ = lab[0] + 0.3963377774 * lab[1] + 0.2158037573 * lab[2]
    m_ = lab[0] - 0.1055613458 * lab[1] - 0.0638541728 * lab[2]
    s_ = lab[0] - 0.0894841775 * lab[1] - 1.2914855480 * lab[2]
    lms = np.array([l_, m_, s_]) ** 3
    lin = np.array(
        [
            4.0767416621 * lms[0] - 3.3077115913 * lms[1] + 0.2309699292 * lms[2],
            -1.2684380046 * lms[0] + 2.6097574011 * lms[1] - 0.3413193965 * lms[2],
            -0.0041960863 * lms[0] - 0.7034186147 * lms[1] + 1.7076147010 * lms[2],
        ]
    )
    lin = np.clip(lin, 0.0, 1.0)
    srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return rgb_to_hex(srgb)
