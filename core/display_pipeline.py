"""Tone mapping och display transform pipeline för HDR-bilder."""

from __future__ import annotations

import numpy as np


def decode_srgb(rgb: np.ndarray) -> np.ndarray:
    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        np.power((rgb + 0.055) / 1.055, 2.4)
    ).astype(np.float32)


def decode_logc3(rgb: np.ndarray) -> np.ndarray:
    a, b, c, d = 5.555556, 0.052272, 0.247190, 0.385537
    e, f       = 5.367655, 0.092809
    lin_cut    = e * (1.0 / 512.0) + f
    return np.where(
        rgb >= lin_cut,
        (np.power(10.0, (rgb - d) / c) - b) / a,
        (rgb - f) / e
    ).astype(np.float32)


def decode_logc4(rgb: np.ndarray) -> np.ndarray:
    a, b = 0.9072394738, 0.0927605262
    t    = (rgb - b) / a
    min6 = 2.0 ** -6
    return np.where(
        t > 0.0,
        np.power(2.0, t * 20.0 - 6.0) - min6,
        t * min6
    ).astype(np.float32)


def decode_slog3(rgb: np.ndarray) -> np.ndarray:
    lin_cut = 0.030001222851889303
    return np.where(
        rgb >= lin_cut,
        np.power(10.0, (rgb - 0.598206) / 0.2100755) * 0.19 - 0.01,
        (rgb * 1023.0 - 95.0) / (171.2102946929 - 95.0) * 0.01125
    ).astype(np.float32)


def decode_vlog(rgb: np.ndarray) -> np.ndarray:
    b, c, d = 0.00873, 0.241514, 0.598206
    return np.where(
        rgb >= 0.181,
        np.power(10.0, (rgb - d) / c) - b,
        (rgb - 0.125) / 5.6
    ).astype(np.float32)


COLORSPACE_DECODERS = {
    'linear': None,
    'srgb':   decode_srgb,
    'rec709': decode_srgb,
    'logc3':  decode_logc3,
    'logc4':  decode_logc4,
    'slog3':  decode_slog3,
    'vlog':   decode_vlog,
}


def decode_colorspace(rgb: np.ndarray, colorspace: str) -> np.ndarray:
    decoder = COLORSPACE_DECODERS.get(colorspace)
    return decoder(rgb) if decoder is not None else rgb


def apply_exposure(pixels: np.ndarray, ev: float) -> np.ndarray:
    """Justera exponering i steg (stops).

    Args:
        pixels: Linjära pixelvärden (float32).
        ev: Exponeringsjustering i stops (+1 = dubbelt ljusare).

    Returns:
        Justerad array med samma shape.
    """
    return pixels * (2.0 ** ev)


def tone_map_reinhard(pixels: np.ndarray) -> np.ndarray:
    """Reinhard tone mapping: x / (x + 1).

    Komprimerar HDR-värden till 0-1 med mjuk roll-off.
    """
    return pixels / (pixels + 1.0)


def tone_map_filmic(pixels: np.ndarray) -> np.ndarray:
    """ACES filmic tone mapping (Narkowicz 2015).

    Ger en filmisk kurva med bra kontrast och mättnad.
    """
    a = 2.51
    b = 0.03
    c = 2.43
    d = 0.59
    e = 0.14
    return np.clip(
        (pixels * (a * pixels + b)) / (pixels * (c * pixels + d) + e),
        0.0, 1.0
    )


def tone_map_clamp(pixels: np.ndarray) -> np.ndarray:
    """Enkel clamp till 0-1 utan tone mapping."""
    return np.clip(pixels, 0.0, 1.0)


def apply_gamma(pixels: np.ndarray, gamma: float) -> np.ndarray:
    """Applicera display-gamma.

    Args:
        pixels: Värden i 0-1 (efter tone mapping).
        gamma: Display-gamma (2.2 för sRGB-liknande).

    Returns:
        Gamma-korrigerad array.
    """
    return np.power(np.clip(pixels, 0.0, 1.0), 1.0 / gamma)


# Uppslagstabell för tone mapping-operatorer
TONE_MAPPERS = {
    'reinhard': tone_map_reinhard,
    'filmic': tone_map_filmic,
    'clamp': tone_map_clamp,
}


def apply_display_transform(
    linear_pixels: np.ndarray,
    exposure: float = 0.0,
    gamma: float = 2.2,
    tone_mapping: str = 'reinhard',
    colorspace: str = 'linear'
) -> np.ndarray:
    """Fullständig display transform pipeline.

    Pipeline: Linjär → Exponering → Tone Map → Gamma → uint16

    Hanterar både 3-kanals (RGB) och 4-kanals (RGBA) input.
    Alpha-kanalen passeras igenom oförändrad.

    Args:
        linear_pixels: Float32 array med shape (H, W, 3) eller (H, W, 4).
        exposure: Exponeringsjustering i stops.
        gamma: Display-gamma.
        tone_mapping: Tone mapping-operator ('reinhard', 'filmic', 'clamp').

    Returns:
        uint16 array redo för QImage, shape (H, W, 3 eller 4).
    """
    has_alpha = linear_pixels.shape[2] == 4

    if has_alpha:
        rgb = linear_pixels[:, :, :3]
        alpha = linear_pixels[:, :, 3:4]
    else:
        rgb = linear_pixels

    # 0. Colorspace decode
    rgb = decode_colorspace(rgb, colorspace)

    # 1. Exponering (linjärt färgrum)
    rgb = apply_exposure(rgb, exposure)

    # 2. Tone mapping (komprimera HDR → 0-1)
    tone_mapper = TONE_MAPPERS.get(tone_mapping, tone_map_reinhard)
    rgb = tone_mapper(rgb)

    # 3. Gamma-korrigering
    rgb = apply_gamma(rgb, gamma)

    # 4. Konvertera till 16-bit
    rgb_16 = np.clip(rgb * 65535.0, 0, 65535).astype(np.uint16)

    if has_alpha:
        alpha_16 = np.clip(alpha * 65535.0, 0, 65535).astype(np.uint16)
        return np.concatenate([rgb_16, alpha_16], axis=2)
    else:
        return rgb_16
