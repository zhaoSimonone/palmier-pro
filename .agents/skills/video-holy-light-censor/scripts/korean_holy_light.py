#!/usr/bin/env python3
"""Pink hand-lettered Korean holy-light look for the video censor pipeline."""
from __future__ import annotations

import glob
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEFAULT_TEXT = "너무 귀여워"
COMPACT_STRENGTH = 0.87
WIDE_STRENGTH = 0.90
ANGLE = 17.0
INK = (228, 122, 156, 240)
INK_SOFT = (232, 145, 172, 205)
PAD_FRACTION = 0.21

FONT_GLOBS = (
    "/System/Library/AssetsV2/**/NanumScript.ttc",
    "/System/Library/Fonts/NanumScript.ttc",
    "/Library/Fonts/NanumScript.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)

# Centres and radii are fractions of the light half-axes so the shape survives
# a change of frame size. Values come from the reference hip-band render.
WIDE_LOBES = (
    (-0.414, 0.111, 0.493, 1.115, 1.00),
    (0.400, 0.068, 0.502, 1.098, 1.00),
    (0.000, 0.128, 0.721, 1.213, 0.74),
)
COMPACT_LOBES = (
    (-0.428, 0.064, 0.298, 0.660, 1.00, 3),
    (0.367, -0.064, 0.353, 0.617, 1.00, 3),
    (-0.023, 0.009, 0.256, 0.298, 0.12, 2),
)


def resolve_korean_font() -> tuple[str, int] | None:
    for pattern in FONT_GLOBS:
        for path in sorted(glob.glob(pattern, recursive=True)):
            if os.path.isfile(path):
                return path, (1 if "NanumScript" in path else 0)
    return None


def heart(draw, x: float, y: float, radius: float, color) -> None:
    draw.ellipse((x - radius, y - radius, x, y), fill=color)
    draw.ellipse((x, y - radius, x + radius, y), fill=color)
    draw.polygon(((x - radius, y), (x + radius, y), (x, y + radius * 1.3)), fill=color)


def sparkle(draw, x: float, y: float, radius: float, color, width: int) -> None:
    draw.line((x - radius, y, x + radius, y), fill=color, width=width)
    draw.line((x, y - radius, x, y + radius), fill=color, width=width)


def parse_lobes(text: str) -> tuple[tuple[float, float, float, float], ...]:
    """Parse `dx,dy,rx,ry;...` lobes in source pixels relative to the light centre."""
    lobes = []
    for part in text.split(";"):
        values = tuple(float(value.strip()) for value in part.split(","))
        if len(values) != 4 or not all(math.isfinite(v) for v in values):
            raise ValueError("--holy-lobes entries must be dx,dy,rx,ry")
        if values[2] <= 0 or values[3] <= 0:
            raise ValueError("--holy-lobes radii must be positive")
        lobes.append(values)
    if not lobes:
        raise ValueError("--holy-lobes needs at least one lobe")
    return tuple(lobes)


def build_korean_holy_light(rx: float, ry: float, strength: float, text: str,
                            compact: bool = False,
                            font: tuple[str, int] | None = None,
                            lobes: tuple[tuple[float, float, float, float], ...] | None = None
                            ) -> tuple[np.ndarray, np.ndarray]:
    """Feathered white light lobes plus a pink lettering decal."""
    if rx <= 0 or ry <= 0:
        raise ValueError("holy light half-axes must be positive")
    if not 0.0 < strength <= 1.0:
        raise ValueError("holy light strength must be in (0, 1]")

    pad = max(24, int(PAD_FRACTION * rx))
    if lobes is not None:
        rx = max(rx, max(abs(dx) + 1.3 * lrx for dx, dy, lrx, lry in lobes))
        ry = max(ry, max(abs(dy) + 1.3 * lry for dx, dy, lrx, lry in lobes))
    width, height = int(2 * rx + 2 * pad), int(2 * ry + 2 * pad)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = width / 2.0, height / 2.0
    presets = COMPACT_LOBES if compact else WIDE_LOBES

    alpha = np.zeros((height, width), np.float32)
    if lobes is not None:
        for dx, dy, lrx, lry in lobes:
            lx, ly = cx + dx, cy + dy
            d = np.sqrt(((xx - lx) / lrx) ** 2 + ((yy - ly) / lry) ** 2)
            t = np.clip((1.32 - d) / 0.85, 0.0, 1.0)
            contribution = strength * (t * t * (3 - 2 * t))
            alpha = 1.0 - (1.0 - alpha) * (1.0 - np.clip(contribution, 0.0, 1.0))
        # Keep the garment between the two lobes readable.
        alpha *= (1.0 - 0.32 * np.exp(-((xx - cx) / (rx * 0.16)) ** 2))
        halo = 0.06 * np.exp(-2.0 * (((xx - cx) / (rx * 0.5)) ** 2 +
                                     ((yy - cy) / (ry * 0.55)) ** 2))
    else:
        for lobe in presets:
            dx, dy, fx, fy, weight = lobe[:5]
            lx, ly = cx + dx * rx, cy + dy * ry
            lrx, lry = max(fx * rx, 1.0), max(fy * ry, 1.0)
            if compact:
                power = lobe[5]
                d = (np.abs((xx - lx) / lrx) ** power +
                     np.abs((yy - ly) / lry) ** power) ** (1.0 / power)
                t = np.clip((1.30 - d) / 0.80, 0.0, 1.0)
                contribution = strength * weight * (t * t * (3 - 2 * t))
            else:
                d2 = ((xx - lx) / lrx) ** 2 + ((yy - ly) / lry) ** 2
                contribution = strength * weight * np.exp(-1.75 * d2)
            alpha = 1.0 - (1.0 - alpha) * (1.0 - np.clip(contribution, 0.0, 1.0))
        if compact:
            d2w = ((xx - cx) / (rx * 0.55)) ** 2 + ((yy - cy) / (ry * 0.62)) ** 2
            halo = 0.08 * np.exp(-2.0 * d2w)
        else:
            d2w = ((xx - cx) / (rx * 1.22)) ** 2 + ((yy - cy) / (ry * 1.40)) ** 2
            halo = 0.20 * np.exp(-1.9 * d2w)
    alpha = np.clip(1.0 - (1.0 - alpha) * (1.0 - halo), 0.0, 0.94).astype(np.float32)
    if lobes is not None:
        alpha = cv2.GaussianBlur(alpha, (0, 0), 15.0).astype(np.float32)

    deco = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(deco)
    letters = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_letters = ImageDraw.Draw(letters)
    if font is None:
        font = resolve_korean_font()
    if text and font is None:
        raise ValueError("Korean lettering needs NanumScript.ttc or AppleSDGothicNeo.ttc")
    if text:
        big = ImageFont.truetype(font[0], max(12, int(height * 0.205)), index=font[1])
        bbox = draw_letters.textbbox((0, 0), text, font=big)
        tw = bbox[2] - bbox[0]
        draw_letters.text(((width - tw) / 2 - bbox[0], height * 0.40 - bbox[1]),
                          text, font=big, fill=INK)
    if font is not None:
        small = ImageFont.truetype(font[0], max(10, int(height * 0.105)), index=font[1])
        draw.text((width * 0.735, height * 0.235), "”", font=small, fill=INK)
        draw.text((width * 0.185, height * 0.245), "“", font=small, fill=INK_SOFT)
        draw.text((width * 0.660, height * 0.635), "!!", font=small, fill=INK)
        draw.text((width * 0.150, height * 0.690), "!", font=small, fill=INK_SOFT)

    for i in range(9):
        t = i / 8
        px = width * (0.155 + 0.40 * t)
        py = height * (0.755 - 0.075 * math.sin(t * math.pi))
        draw.line((px, py, px + width * 0.026, py - height * 0.010),
                  fill=INK_SOFT, width=max(2, int(height * 0.010)))
    for fx, fy, r in ((0.245, 0.615, 0.013), (0.795, 0.505, 0.011),
                      (0.300, 0.300, 0.009), (0.625, 0.745, 0.010)):
        radius = height * r
        draw.ellipse((width * fx - radius, height * fy - radius,
                      width * fx + radius, height * fy + radius), fill=INK_SOFT)
    heart(draw, width * 0.825, height * 0.665, height * 0.030, INK)
    heart(draw, width * 0.105, height * 0.505, height * 0.022, INK_SOFT)
    for fx, fy, r in ((0.115, 0.365, 0.032), (0.885, 0.355, 0.026),
                      (0.735, 0.775, 0.020)):
        sparkle(draw, width * fx, height * fy, height * r, INK_SOFT,
                max(2, int(height * 0.009)))

    resampling = Image.Resampling
    deco_layer = np.asarray(deco.rotate(ANGLE, resample=resampling.BICUBIC,
                                        center=(cx, cy)), dtype=np.uint8).copy()
    # Only the small decorations fade with the light; the lettering stays solid.
    deco_layer[..., 3] = (deco_layer[..., 3].astype(np.float32) *
                          np.clip(alpha * 1.25, 0.0, 1.0) ** 1.25).astype(np.uint8)
    rotated_letters = letters.rotate(ANGLE, resample=resampling.BICUBIC, center=(cx, cy))
    sticker = np.asarray(Image.alpha_composite(Image.fromarray(deco_layer),
                                               rotated_letters), dtype=np.uint8)
    return alpha, sticker


def apply_korean_holy_light(frame: np.ndarray, cx: float, cy: float,
                            alpha: np.ndarray, sticker: np.ndarray,
                            blur_sigma: float = 30.0, flicker: float = 1.0) -> None:
    """Blur only inside the light, whiten it, then composite the pink decal."""
    height, width = alpha.shape
    x0, y0 = int(round(cx - width / 2)), int(round(cy - height / 2))
    ax0, ay0 = max(0, -x0), max(0, -y0)
    x0, y0 = max(0, x0), max(0, y0)
    x1 = min(frame.shape[1], x0 + width - ax0)
    y1 = min(frame.shape[0], y0 + height - ay0)
    if x1 <= x0 or y1 <= y0:
        return

    light = alpha[ay0:ay0 + (y1 - y0), ax0:ax0 + (x1 - x0)]
    weight = np.clip(light * 1.12, 0.0, 1.0)[..., None]
    original = frame[y0:y1, x0:x1].astype(np.float32)
    if blur_sigma > 0:
        soft = cv2.GaussianBlur(frame, (0, 0), blur_sigma).astype(np.float32)[y0:y1, x0:x1]
        region = original * (1 - weight) + soft * weight
    else:
        region = original
    region = region * (1 - light[..., None]) + 255.0 * light[..., None]
    decal = sticker[ay0:ay0 + (y1 - y0), ax0:ax0 + (x1 - x0)]
    decal_alpha = decal[..., 3:4].astype(np.float32) / 255.0 * flicker
    decal_rgb = decal[..., :3][..., ::-1].astype(np.float32)
    frame[y0:y1, x0:x1] = np.clip(
        region * (1 - decal_alpha) + decal_rgb * decal_alpha, 0, 255).astype(np.uint8)
