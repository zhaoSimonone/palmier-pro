#!/usr/bin/env python3
"""Blur a tracked region of a video with a soft feathered mask, preserving audio."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from korean_holy_light import (COMPACT_STRENGTH, DEFAULT_TEXT, WIDE_STRENGTH,
                               apply_korean_holy_light, build_korean_holy_light)

HUE_LO, HUE_HI = 5, 34
SAT_LO, SAT_HI = 85, 180
VAL_LO, VAL_HI = 120, 250


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def probe(ffprobe: str, path: Path) -> dict:
    result = run([
        ffprobe, "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,duration,width,height,r_frame_rate,avg_frame_rate,"
        "nb_frames,sample_rate,channels",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def parse_pair(text: str, label: str) -> tuple[float, float]:
    parts = text.split(",")
    if len(parts) != 2:
        raise ValueError(f"{label} must be X,Y")
    return finite(parts[0], f"{label}.x"), finite(parts[1], f"{label}.y")


def parse_rect(text: str, label: str) -> tuple[float, float, float, float]:
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError(f"{label} must be X,Y,W,H")
    x, y, w, h = (finite(p, f"{label}[{i}]") for i, p in enumerate(parts))
    if w <= 0 or h <= 0:
        raise ValueError(f"{label} width and height must be positive")
    return x, y, w, h


def skin_mask(img: np.ndarray, hue: tuple[int, int], sat: tuple[int, int], val: tuple[int, int]) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0].astype(np.int16)
    s = hsv[..., 1].astype(np.int16)
    v = hsv[..., 2].astype(np.int16)
    m = ((h >= hue[0]) & (h <= hue[1]) & (s >= sat[0]) & (s <= sat[1]) &
         (v >= val[0]) & (v <= val[1])).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    return m


def component_at(mask: np.ndarray, px: float, py: float, window: tuple[int, int, int, int],
                 band: tuple[int, int] | None, radius: int, min_area: int) -> dict | None:
    """Bounding box of the mask component nearest to (px, py) inside window."""
    x0, y0, x1, y1 = window
    sub = mask[y0:y1, x0:x1].copy()
    if band is not None:
        lo = max(0, band[0] - x0)
        hi = min(sub.shape[1], band[1] - x0)
        if hi > lo:
            sub[:, lo:hi] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(sub, 8)
    best = None
    for dy in range(-radius, radius + 1, 2):
        for dx in range(-radius, radius + 1, 2):
            x, y = int(px + dx) - x0, int(py + dy) - y0
            if not (0 <= y < sub.shape[0] and 0 <= x < sub.shape[1]):
                continue
            k = labels[y, x]
            if k == 0:
                continue
            bx, by, bw, bh, area = stats[k]
            if area < min_area:
                continue
            distance = dx * dx + dy * dy
            if best is None or distance < best[0]:
                best = (distance, bx, by, bw, bh, area)
    if best is None:
        return None
    _, bx, by, bw, bh, area = best
    return {"x": int(bx + x0), "y": int(by + y0), "w": int(bw), "h": int(bh), "area": int(area),
            "cx": bx + x0 + bw / 2.0, "cy": by + y0 + bh / 2.0}


def expand(box: dict, margin: int, width: int, height: int) -> tuple[int, int, int, int]:
    return (max(0, box["x"] - margin), max(0, box["y"] - margin),
            min(width, box["x"] + box["w"] + margin), min(height, box["y"] + box["h"] + margin))


def track_skin(mask_paths: list[Path], reference: int, seed: tuple[float, float],
               band: tuple[int, int] | None, width: int, height: int,
               margin: int, radius: int, min_area: int) -> list[dict | None]:
    """Track the skin component holding the seed from the reference frame outwards."""
    count = len(mask_paths)
    track: list[dict | None] = [None] * count

    def detect(index: int, px: float, py: float, window) -> dict | None:
        mask = cv2.imread(str(mask_paths[index]), cv2.IMREAD_GRAYSCALE)
        return component_at(mask, px, py, window, band, radius, min_area)

    origin = detect(reference, seed[0], seed[1], (0, 0, width, height))
    if origin is None:
        raise ValueError(f"no skin region found at seed {seed[0]:.0f},{seed[1]:.0f}")
    track[reference] = origin
    for direction in (1, -1):
        index = reference
        current = origin
        while True:
            nxt = index + direction
            if nxt < 0 or nxt >= count:
                break
            found = detect(nxt, current["cx"], current["cy"], expand(current, margin, width, height))
            track[nxt] = found if found else dict(current)
            if found:
                current = found
            index = nxt
    return track


def track_template(frame_paths: list[Path], reference: int, seed: tuple[float, float],
                   size: tuple[int, int], radius: int) -> list[dict | None]:
    """Track a fixed-size patch around the seed by normalized cross-correlation."""
    count = len(frame_paths)
    half_w, half_h = max(1, size[0] // 2), max(1, size[1] // 2)
    first = cv2.imread(str(frame_paths[reference]), cv2.IMREAD_GRAYSCALE)
    sx, sy = int(seed[0]), int(seed[1])
    template = first[max(0, sy - half_h):sy + half_h, max(0, sx - half_w):sx + half_w]
    if template.size == 0:
        raise ValueError("seed point is outside the frame")
    th, tw = template.shape[:2]
    track: list[dict | None] = [None] * count
    position = (float(sx), float(sy))
    track[reference] = {"x": sx - tw // 2, "y": sy - th // 2, "w": tw, "h": th,
                         "area": tw * th, "cx": position[0], "cy": position[1]}
    for direction in (1, -1):
        index = reference
        while True:
            nxt = index + direction
            if nxt < 0 or nxt >= count:
                break
            frame = cv2.imread(str(frame_paths[nxt]), cv2.IMREAD_GRAYSCALE)
            px, py = position
            x0 = max(0, int(px - tw - radius)); x1 = min(frame.shape[1], int(px + tw + radius))
            y0 = max(0, int(py - th - radius)); y1 = min(frame.shape[0], int(py + th + radius))
            window = frame[y0:y1, x0:x1]
            if window.shape[0] < th or window.shape[1] < tw:
                track[nxt] = dict(track[index])
            else:
                response = cv2.matchTemplate(window, template, cv2.TM_CCOEFF_NORMED)
                _, _, _, location = cv2.minMaxLoc(response)
                position = (x0 + location[0] + tw / 2.0, y0 + location[1] + th / 2.0)
                track[nxt] = {"x": int(position[0] - tw / 2), "y": int(position[1] - th / 2),
                              "w": tw, "h": th, "area": tw * th,
                              "cx": position[0], "cy": position[1]}
            index = nxt
    return track


def smooth_track(track: list[dict | None], sigma: float) -> list[dict]:
    """Fill gaps, then smooth centre positions so the mask does not jitter."""
    filled: list[dict] = []
    last = None
    for box in track:
        if box is None:
            box = dict(last) if last else {"x": 0, "y": 0, "w": 10, "h": 10, "area": 100,
                                           "cx": 0.0, "cy": 0.0}
        filled.append(box)
        last = box
    if sigma > 0 and len(filled) > 3:
        for key in ("cx", "cy"):
            values = np.array([b[key] for b in filled], np.float64)
            values = cv2.GaussianBlur(values.reshape(-1, 1), (0, 0), sigma).ravel()
            for box, value in zip(filled, values):
                box[key] = float(value)
    return filled


def ellipse_mask(x0: int, y0: int, x1: int, y1: int, cx: float, cy: float,
                 rx: float, ry: float, plateau: float) -> np.ndarray:
    """Feathered elliptical falloff over the ROI (x0,y0,x1,y1) only."""
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    d = np.sqrt(((xx - cx) / max(rx, 1.0)) ** 2 + ((yy - cy) / max(ry, 1.0)) ** 2)
    t = np.clip((1.0 - d) / max(1.0 - plateau, 1e-3), 0.0, 1.0)
    return (t * t * (3 - 2 * t)).astype(np.float32)


def white_core(rx: float, ry: float, peak: float) -> np.ndarray:
    height = max(3, int(ry * 2) + 3)
    width = max(3, int(rx * 2) + 3)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    d = np.sqrt(((xx - width / 2.0) / max(rx, 1.0)) ** 2 + ((yy - height / 2.0) / max(ry, 1.0)) ** 2)
    return (np.clip(1.0 - d, 0.0, 1.0) ** 1.15 * peak).astype(np.float32)


STICKER_FONTS = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


def draw_heart(draw, x: float, y: float, radius: float, color) -> None:
    draw.ellipse((x - radius, y - radius, x, y), fill=color)
    draw.ellipse((x, y - radius, x + radius, y), fill=color)
    draw.polygon(((x - radius, y), (x + radius, y), (x, y + radius * 1.25)), fill=color)


def build_sticker_glow(rx: float, ry: float, scale: float, strength: float,
                       text: str) -> tuple[np.ndarray, np.ndarray]:
    """Feathered white light patch plus a hand-drawn sticker decal."""
    from PIL import Image, ImageDraw, ImageFont

    rx, ry = rx * scale, ry * scale
    width = int(2 * rx + 120)
    height = int(2 * ry + 120)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = width / 2.0, height / 2.0
    d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    core = np.clip((1.0 - d) / 0.42, 0.0, 1.0)
    core = core * core * (3 - 2 * core)
    dh = np.sqrt(((xx - cx) / (rx * 1.32)) ** 2 + ((yy - cy) / (ry * 1.32)) ** 2)
    halo = np.clip(1.0 - dh, 0.0, 1.0) ** 1.7 * 0.22
    alpha = np.clip(core * strength + halo * (1 - core * strength), 0.0, 1.0).astype(np.float32)

    ink = (255, 92, 122, 255)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font_path = next((p for p in STICKER_FONTS if os.path.isfile(p)), None)
    if font_path and text:
        font = ImageFont.truetype(font_path, max(18, int(height * 0.17)))
        bbox = draw.textbbox((0, 0), text, font=font)
        tx = (width - (bbox[2] - bbox[0])) / 2 - bbox[0]
        draw.text((tx, height * 0.30), text, font=font, fill=ink,
                  stroke_width=max(3, int(height * 0.012)), stroke_fill=(255, 255, 255, 235))
        small = ImageFont.truetype(font_path, max(14, int(height * 0.10)))
        draw.text((width * 0.13, height * 0.22), "!!", font=small, fill=ink)
        draw_heart(draw, width * 0.79, height * 0.60, height * 0.042, ink)
        draw_heart(draw, width * 0.15, height * 0.68, height * 0.032, ink)
    for fx, fy, radius in ((0.24, 0.15, 0.035), (0.83, 0.23, 0.028), (0.73, 0.79, 0.022)):
        px, py = width * fx, height * fy
        r = height * radius
        draw.line((px - r, py, px + r, py), fill=ink, width=3)
        draw.line((px, py - r, px, py + r), fill=ink, width=3)
    resampling = getattr(Image, "Resampling", Image)
    sticker = np.asarray(layer.rotate(-8, resample=resampling.BICUBIC), dtype=np.uint8)
    return alpha, sticker


def apply_sticker_glow(frame: np.ndarray, cx: float, cy: float,
                       alpha: np.ndarray, sticker: np.ndarray, flicker: float) -> None:
    """Composite the light patch and its decals centred on the tracked region."""
    height, width = alpha.shape
    x0, y0 = int(round(cx - width / 2)), int(round(cy - height / 2))
    ax0, ay0 = max(0, -x0), max(0, -y0)
    x0, y0 = max(0, x0), max(0, y0)
    x1 = min(frame.shape[1], x0 + width - ax0)
    y1 = min(frame.shape[0], y0 + height - ay0)
    if x1 <= x0 or y1 <= y0:
        return
    light = alpha[ay0:ay0 + (y1 - y0), ax0:ax0 + (x1 - x0)]
    region = frame[y0:y1, x0:x1].astype(np.float32)
    region = region * (1 - light[..., None]) + 255.0 * light[..., None]
    decal = sticker[ay0:ay0 + (y1 - y0), ax0:ax0 + (x1 - x0)]
    decal_alpha = decal[..., 3:4].astype(np.float32) / 255.0 * flicker
    decal_rgb = decal[..., :3][..., ::-1].astype(np.float32)
    region = region * (1 - decal_alpha) + decal_rgb * decal_alpha
    frame[y0:y1, x0:x1] = np.clip(region, 0, 255).astype(np.uint8)


def parse_segment(text: str, label: str, default_smooth: float) -> dict:
    fields = {}
    for part in text.split(";"):
        key, separator, value = part.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"{label} must be 'start=S;end=E;region=X,Y,W,H;offset=DX,DY;smooth=P'")
        fields[key.strip()] = value.strip()
    missing = {"start", "end", "region"} - fields.keys()
    if missing:
        raise ValueError(f"{label} is missing {', '.join(sorted(missing))}")
    rect = tuple(finite(v, f"{label}.region[{i}]") for i, v in enumerate(fields["region"].split(",")))
    if len(rect) != 4 or rect[2] <= 0 or rect[3] <= 0:
        raise ValueError(f"{label}.region must be X,Y,W,H")
    smooth = finite(fields.get("smooth", str(default_smooth)), f"{label}.smooth")
    if smooth < 0:
        raise ValueError(f"{label}.smooth must not be negative")
    return {"start": finite(fields["start"], f"{label}.start"),
            "end": finite(fields["end"], f"{label}.end"),
            "rects": [rect], "seeds": [],
            "offset": parse_pair(fields.get("offset", "0,0"), f"{label}.offset"),
            "smooth": smooth, "reference": -1}


def build_segments(args: argparse.Namespace, fps: float, total: int,
                   duration: float, offset: tuple[float, float]) -> list[dict]:
    if args.segment:
        raw = [parse_segment(text, f"--segment[{i}]", args.smooth)
               for i, text in enumerate(args.segment)]
    else:
        start = max(0.0, finite(args.start, "start"))
        end = duration if args.end is None else finite(args.end, "end")
        raw = [{"start": start, "end": end,
                "rects": [parse_rect(r, "--region") for r in args.region],
                "seeds": [parse_pair(s, "--seed") for s in args.seed],
                "offset": offset, "smooth": args.smooth, "reference": args.reference_frame}]
    segments = []
    for item in raw:
        if item["end"] <= item["start"] or item["end"] > duration:
            raise ValueError("each segment interval must be inside the video duration")
        first = int(round(item["start"] * fps))
        last = min(total, int(round(item["end"] * fps)))
        if last - first < 2:
            raise ValueError("each segment interval is too short to track")
        segments.append({**item, "first": first, "last": last})
    segments.sort(key=lambda seg: seg["first"])
    for previous, current in zip(segments, segments[1:]):
        if current["first"] < previous["last"]:
            raise ValueError("segments must not overlap")
    return segments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--segment", action="append", default=[], metavar="KEY=VALUE;...",
                        help="independent interval; repeat for several intervals. "
                             "Keys: start, end, region=X,Y,W,H, offset=DX,DY, smooth.")
    parser.add_argument("--seed", action="append", default=[], metavar="X,Y",
                        help="point inside the region to obscure; repeat for a second region")
    parser.add_argument("--region", action="append", default=[], metavar="X,Y,W,H",
                        help="explicit rectangle to track instead of skin detection; repeatable")
    parser.add_argument("--band", default="", metavar="X1,X2",
                        help="column range excluded from skin detection so neighbouring regions "
                             "do not merge; defaults to the middle half of the gap between seeds")
    parser.add_argument("--zone-width", type=float, default=0.95,
                        help="zone radius as a multiple of the tracked box width")
    parser.add_argument("--zone-height", type=float, default=0.85,
                        help="zone radius as a multiple of the tracked box height")
    parser.add_argument("--blur", type=float, default=0.30,
                        help="blur sigma as a fraction of the zone half-width")
    parser.add_argument("--sigma-min", type=float, default=16.0)
    parser.add_argument("--sigma-max", type=float, default=26.0,
                        help="upper clamp on sigma in pixels; a large sigma reaches past the "
                             "zone and drags dark neighbours into the blur")
    parser.add_argument("--plateau", type=float, default=0.78,
                        help="inner fraction of the zone that receives full blur")
    parser.add_argument("--core", type=float, default=0.0,
                        help="white core opacity inside the zone, 0 disables it")
    parser.add_argument("--milk", type=float, default=2.0,
                        help="brightness lift applied inside the blur")
    parser.add_argument("--reference-frame", type=int, default=-1,
                        help="frame index inside the interval used to seed tracking; default is the middle")
    parser.add_argument("--smooth", type=float, default=2.0)
    parser.add_argument("--offset", default="0,0", metavar="DX,DY",
                        help="shift the censored zone centre relative to the tracked centre")
    parser.add_argument("--min-area", type=int, default=0,
                        help="smallest skin blob in pixels that may be tracked; "
                             "0 derives it from the frame size")
    parser.add_argument("--hue", default=f"{HUE_LO},{HUE_HI}")
    parser.add_argument("--sat", default=f"{SAT_LO},{SAT_HI}")
    parser.add_argument("--val", default=f"{VAL_LO},{VAL_HI}")
    parser.add_argument("--audio", choices=("copy", "aac"), default="copy")
    parser.add_argument("--sticker-style", action="store_true",
                        help="add a sticker-style white glow over the censored region")
    parser.add_argument("--sticker-look", choices=("emoji", "korean"), default=None,
                        help="sticker appearance; also enables --sticker-style. "
                             "korean uses pink hand-lettered Hangul over soft white lobes")
    parser.add_argument("--sticker-compact", action="store_true",
                        help="korean look: two small hip lobes instead of the wide three-lobe glow")
    parser.add_argument("--holy-size", default="auto", metavar="auto|W,H",
                        help="korean look: light half-width,half-height in source pixels; "
                             "auto derives both from the frame size")
    parser.add_argument("--sticker-text", default=None,
                        help="hand-drawn text on the glow; empty disables the lettering. "
                             "Defaults to 喵~ or 너무 귀여워 by look")
    parser.add_argument("--glow", type=float, default=None,
                        help="opacity of the white light at its centre; defaults to 0.90")
    parser.add_argument("--glow-scale", type=float, default=None,
                        help="light radius relative to the zone radius (emoji, 1.30) "
                             "or to --holy-size (korean, 1.00)")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise ValueError(f"input file not found: {args.input}")
    if args.output.exists():
        raise ValueError("output already exists; choose a new filename")
    if args.output.suffix.lower() != ".mp4":
        raise ValueError("output must be an MP4 file")
    if args.output.resolve() == args.input.resolve():
        raise ValueError("output must differ from the input")
    if args.segment:
        if args.seed or args.region:
            raise ValueError("use either --segment or --seed/--region, not both")
    else:
        if not args.seed and not args.region:
            raise ValueError("provide at least one --seed or --region")
        if args.seed and args.region:
            raise ValueError("use either --seed or --region, not both")
        if len(args.seed) > 2 or len(args.region) > 2:
            raise ValueError("at most two regions are supported")
    if args.blur < 0 or args.core < 0 or args.core > 1 or args.milk < 0:
        raise ValueError("--blur, --core and --milk must be non-negative and --core at most 1")
    if args.zone_width <= 0 or args.zone_height <= 0:
        raise ValueError("--zone-width and --zone-height must be positive")
    if not 0.0 < args.plateau < 1.0:
        raise ValueError("--plateau must be between 0 and 1")
    if args.min_area < 0:
        raise ValueError("--min-area must not be negative")
    look = args.sticker_look or ("emoji" if args.sticker_style else None)
    korean = look == "korean"
    strength = args.glow if args.glow is not None else (
        (COMPACT_STRENGTH if args.sticker_compact else WIDE_STRENGTH) if korean else 0.90)
    glow_scale = args.glow_scale if args.glow_scale is not None else (1.0 if korean else 1.30)
    sticker_text = args.sticker_text if args.sticker_text is not None else (
        DEFAULT_TEXT if korean else "喵~")
    if look and (strength <= 0 or strength > 1 or glow_scale <= 0):
        raise ValueError("--glow must be in (0, 1] and --glow-scale must be positive")
    if args.sticker_compact and not korean:
        raise ValueError("--sticker-compact requires --sticker-look korean")
    holy_size = None
    if korean and args.holy_size != "auto":
        holy_size = parse_pair(args.holy_size, "--holy-size")
        if holy_size[0] <= 0 or holy_size[1] <= 0:
            raise ValueError("--holy-size half-axes must be positive")
    offset = parse_pair(args.offset, "--offset")

    media = probe(args.ffprobe, args.input)
    video = next((s for s in media.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("input has no video stream")
    width, height = int(video["width"]), int(video["height"])
    duration = finite(video.get("duration") or media.get("format", {}).get("duration"),
                      "video duration")
    if duration <= 0:
        raise ValueError("video duration must be positive")
    rate = (video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1").split("/", 1)
    fps = float(rate[0]) / float(rate[1]) if float(rate[1]) > 0 else 30.0
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("could not determine a positive frame rate")
    total = int(video.get("nb_frames") or 0) or max(1, round(duration * fps))

    segments = build_segments(args, fps, total, duration, offset)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".blur-censor-", dir=args.output.parent) as temp_name:
        temp = Path(temp_name)
        out_dir = temp / "rendered"
        out_dir.mkdir()

        hue = tuple(int(v) for v in parse_pair(args.hue, "hue"))
        sat = tuple(int(v) for v in parse_pair(args.sat, "sat"))
        val = tuple(int(v) for v in parse_pair(args.val, "val"))
        seed_points = [parse_pair(s, "--seed") for s in args.seed]
        band = None
        if args.band:
            band = tuple(int(v) for v in parse_pair(args.band, "--band"))
        elif len(seed_points) == 2:
            low = min(seed_points[0][0], seed_points[1][0])
            high = max(seed_points[0][0], seed_points[1][0])
            gap = high - low
            band = (int(low + gap * 0.25), int(high - gap * 0.25))
        min_area = args.min_area or max(400, int(0.0006 * width * height))

        running = 0
        for si, seg in enumerate(segments):
            frames_dir = temp / f"frames_{si}"
            frames_dir.mkdir()
            run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                 "-i", str(args.input),
                 "-vf", f"trim=start_frame={seg['first']}:end_frame={seg['last']},setpts=PTS-STARTPTS",
                 "-fps_mode", "passthrough", str(frames_dir / "%06d.png")])
            frame_paths = sorted(frames_dir.glob("*.png"))
            if len(frame_paths) != seg["last"] - seg["first"]:
                raise ValueError(f"segment {si}: expected {seg['last'] - seg['first']} frames, "
                                 f"decoded {len(frame_paths)}")

            reference = seg["reference"]
            if reference < 0:
                reference = len(frame_paths) // 2
            reference = max(0, min(len(frame_paths) - 1, reference))
            seg["reference"] = reference

            if seg["seeds"]:
                mask_dir = temp / f"masks_{si}"
                mask_dir.mkdir()
                for index, path in enumerate(frame_paths):
                    image = cv2.imread(str(path))
                    cv2.imwrite(str(mask_dir / f"{index + 1:06d}.png"), skin_mask(image, hue, sat, val))
                mask_paths = sorted(mask_dir.glob("*.png"))
                tracks = [track_skin(mask_paths, reference, seed, band, width, height,
                                     margin=24, radius=50, min_area=min_area) for seed in seg["seeds"]]
            else:
                tracks = [track_template(frame_paths, reference,
                                         (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2),
                                         (int(rect[2]), int(rect[3])), radius=60)
                          for rect in seg["rects"]]

            smoothed = [smooth_track(track, seg["smooth"]) for track in tracks]
            if seg["offset"] != (0.0, 0.0):
                for boxes in smoothed:
                    for box in boxes:
                        box["cx"] += seg["offset"][0]
                        box["cy"] += seg["offset"][1]
            seg["tracks"] = smoothed
            seg["paths"] = frame_paths
            seg["render_start"] = running

            if korean and len(smoothed) > 1:
                raise ValueError("the korean look takes one region; its lobes already cover both sides")
            glow_alpha = glow_sticker = None
            holy_blur_sigma = 0.0
            if look:
                if korean:
                    holy_rx, holy_ry = holy_size or (0.60 * width, 0.185 * height)
                    holy_rx, holy_ry = holy_rx * glow_scale, holy_ry * glow_scale
                    glow_alpha, glow_sticker = build_korean_holy_light(
                        holy_rx, holy_ry, strength, sticker_text, args.sticker_compact)
                    holy_blur_sigma = (0.060 if args.sticker_compact else 0.075) * holy_rx
                else:
                    ref_box = smoothed[0][reference]
                    glow_alpha, glow_sticker = build_sticker_glow(
                        max(12.0, args.zone_width * ref_box["w"]),
                        max(12.0, args.zone_height * ref_box["h"]),
                        glow_scale, strength, sticker_text)

            for index, path in enumerate(frame_paths):
                image = cv2.imread(str(path))
                out = image.astype(np.float32)
                # A second elliptical zone would wash out the garment between the korean lobes.
                blur_tracks = [] if korean else smoothed
                for boxes in blur_tracks:
                    box = boxes[index]
                    cx, cy = box["cx"], box["cy"]
                    rx = max(12.0, args.zone_width * box["w"])
                    ry = max(12.0, args.zone_height * box["h"])
                    sigma = float(np.clip(args.blur * rx, args.sigma_min, args.sigma_max))
                    pad = int(3 * sigma) + 4
                    x0 = max(0, int(cx - rx - pad)); x1 = min(width, int(cx + rx + pad))
                    y0 = max(0, int(cy - ry - pad)); y1 = min(height, int(cy + ry + pad))
                    patch = image[y0:y1, x0:x1]
                    blurred = cv2.GaussianBlur(patch, (0, 0), sigma).astype(np.float32)
                    zone = ellipse_mask(x0, y0, x1, y1, cx, cy, rx, ry, args.plateau)
                    out[y0:y1, x0:x1] = (out[y0:y1, x0:x1] * (1 - zone[:, :, None]) +
                                         (blurred + args.milk * zone[:, :, None]) * zone[:, :, None])
                out = np.clip(out, 0, 255).astype(np.uint8)
                if args.core > 0 and not korean:
                    for boxes in smoothed:
                        box = boxes[index]
                        cx, cy = box["cx"], box["cy"]
                        rx = max(12.0, args.zone_width * box["w"])
                        ry = max(12.0, args.zone_height * box["h"])
                        core = white_core(rx * 0.36, ry * 0.36, args.core)
                        ch, cw = core.shape
                        sx = int(round(cx - cw / 2)); sy = int(round(cy - ch / 2))
                        ax0, ay0 = max(0, -sx), max(0, -sy)
                        sx = max(0, sx); sy = max(0, sy)
                        sx1 = min(width, sx + cw - ax0); sy1 = min(height, sy + ch - ay0)
                        if sx1 <= sx or sy1 <= sy:
                            continue
                        layer = core[ay0:ay0 + (sy1 - sy), ax0:ax0 + (sx1 - sx)]
                        region = out[sy:sy1, sx:sx1].astype(np.float32)
                        out[sy:sy1, sx:sx1] = np.clip(
                            region * (1 - layer[:, :, None]) + 255.0 * layer[:, :, None], 0, 255).astype(np.uint8)
                if glow_alpha is not None:
                    flicker = 1.0 + (0.05 if korean else 0.06) * math.sin(index * 0.35)
                    for boxes in smoothed:
                        box = boxes[index]
                        if korean:
                            apply_korean_holy_light(out, box["cx"], box["cy"],
                                                    glow_alpha, glow_sticker,
                                                    blur_sigma=holy_blur_sigma,
                                                    flicker=flicker)
                        else:
                            apply_sticker_glow(out, box["cx"], box["cy"],
                                               glow_alpha, glow_sticker, flicker)
                cv2.imwrite(str(out_dir / f"{running + index + 1:06d}.png"), out)
            running += len(frame_paths)

        chains, labels = [], []
        cursor = 0
        index = 0
        for seg in segments:
            if seg["first"] > cursor:
                chains.append(f"[0:v]trim=start_frame={cursor}:end_frame={seg['first']},"
                              f"setpts=PTS-STARTPTS[c{index}]")
                labels.append(f"[c{index}]")
                index += 1
            render_end = seg["render_start"] + (seg["last"] - seg["first"])
            chains.append(f"[1:v]trim=start_frame={seg['render_start']}:end_frame={render_end},"
                          f"setpts=PTS-STARTPTS[c{index}]")
            labels.append(f"[c{index}]")
            index += 1
            cursor = seg["last"]
        if cursor < total:
            chains.append(f"[0:v]trim=start_frame={cursor},setpts=PTS-STARTPTS[c{index}]")
            labels.append(f"[c{index}]")
        graph = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1[v]"

        staged = temp / "render.mp4"
        run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(args.input), "-framerate", f"{fps:.12g}", "-i", str(out_dir / "%06d.png"),
             "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-r", f"{fps:.12g}",
             "-c:a", args.audio, "-movflags", "+faststart", str(staged)])
        rendered = probe(args.ffprobe, staged)
        if not any(s.get("codec_type") == "video" for s in rendered.get("streams", [])):
            raise ValueError("rendered output has no video stream")
        os.replace(staged, args.output)

    primary = segments[0]
    print(json.dumps({
        "output": str(args.output.resolve()),
        "input": str(args.input.resolve()),
        "interval": [primary["start"], primary["end"]],
        "frames": [primary["first"], primary["last"]],
        "referenceFrame": primary["reference"],
        "videoFPS": fps,
        "videoSize": [width, height],
        "regions": len(primary["tracks"]),
        "mode": "skin-seed" if primary["seeds"] else "template-rect",
        "blurFraction": args.blur,
        "zoneOffset": list(primary["offset"]),
        "stickerStyle": bool(look),
        "stickerLook": look or "",
        "stickerText": sticker_text if look else "",
        "stickerCompact": bool(korean and args.sticker_compact),
        "audioMode": args.audio,
        "segments": [
            {"start": seg["start"], "end": seg["end"],
             "frames": [seg["first"], seg["last"]],
             "referenceFrame": seg["reference"], "offset": list(seg["offset"]),
             "smooth": seg["smooth"], "regions": len(seg["tracks"])}
            for seg in segments
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"error: {detail}", file=sys.stderr)
        raise SystemExit(2)
