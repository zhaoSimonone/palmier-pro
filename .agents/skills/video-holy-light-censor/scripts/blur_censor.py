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
                   size: tuple[int, int], radius: int, pad: int = 0,
                   min_score: float = 0.0) -> list[dict | None]:
    """Track a fixed-size patch around the seed by normalized cross-correlation.

    `pad` grows the matched template with surrounding context while the reported
    box keeps the requested region size, so a smooth target with no texture of
    its own can still be locked onto by the detail around it. `radius` bounds
    how far the centre may move per frame.
    """
    count = len(frame_paths)
    half_w, half_h = max(1, size[0] // 2), max(1, size[1] // 2)
    first = cv2.imread(str(frame_paths[reference]), cv2.IMREAD_GRAYSCALE)
    sx, sy = int(seed[0]), int(seed[1])
    template = first[max(0, sy - half_h - pad):sy + half_h + pad,
                     max(0, sx - half_w - pad):sx + half_w + pad]
    if template.size == 0:
        raise ValueError("seed point is outside the frame")
    th, tw = template.shape[:2]
    track: list[dict | None] = [None] * count
    position = (float(sx), float(sy))
    track[reference] = {"x": sx - size[0] // 2, "y": sy - size[1] // 2, "w": size[0], "h": size[1],
                         "area": size[0] * size[1], "cx": position[0], "cy": position[1]}
    for direction in (1, -1):
        index = reference
        while True:
            nxt = index + direction
            if nxt < 0 or nxt >= count:
                break
            frame = cv2.imread(str(frame_paths[nxt]), cv2.IMREAD_GRAYSCALE)
            px, py = position
            x0 = max(0, int(px - tw // 2 - radius)); x1 = min(frame.shape[1], int(px + tw // 2 + radius + 1))
            y0 = max(0, int(py - th // 2 - radius)); y1 = min(frame.shape[0], int(py + th // 2 + radius + 1))
            window = frame[y0:y1, x0:x1]
            if window.shape[0] < th or window.shape[1] < tw:
                track[nxt] = dict(track[index])
            else:
                response = cv2.matchTemplate(window, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, location = cv2.minMaxLoc(response)
                if score < min_score:
                    track[nxt] = dict(track[index])
                else:
                    position = (x0 + location[0] + tw / 2.0, y0 + location[1] + th / 2.0)
                    track[nxt] = {"x": int(position[0] - size[0] // 2), "y": int(position[1] - size[1] // 2),
                                  "w": size[0], "h": size[1], "area": size[0] * size[1],
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--seed", action="append", default=[], metavar="X,Y",
                        help="point inside the region to obscure; repeat for a second region")
    parser.add_argument("--region", action="append", default=[], metavar="X,Y,W,H",
                        help="explicit rectangle to track instead of skin detection; repeatable")
    parser.add_argument("--track-pad", type=int, default=0,
                        help="extra pixels of context added around the region for matching only; "
                             "the blur still covers the region alone. Raise it when the target is "
                             "smooth and has no texture of its own")
    parser.add_argument("--search-radius", type=int, default=60,
                        help="how far the tracked centre may move per frame, in pixels")
    parser.add_argument("--min-score", type=float, default=0.0,
                        help="hold the previous position when the best match scores below this; "
                             "0 accepts every match")
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
    parser.add_argument("--min-area", type=int, default=0,
                        help="smallest skin blob in pixels that may be tracked; "
                             "0 derives it from the frame size")
    parser.add_argument("--hue", default=f"{HUE_LO},{HUE_HI}")
    parser.add_argument("--sat", default=f"{SAT_LO},{SAT_HI}")
    parser.add_argument("--val", default=f"{VAL_LO},{VAL_HI}")
    parser.add_argument("--audio", choices=("copy", "aac"), default="copy")
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
    if args.track_pad < 0:
        raise ValueError("--track-pad must not be negative")
    if args.search_radius < 0:
        raise ValueError("--search-radius must not be negative")
    if not 0.0 <= args.min_score <= 1.0:
        raise ValueError("--min-score must be between 0 and 1")
    if args.min_area < 0:
        raise ValueError("--min-area must not be negative")

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

    start = max(0.0, finite(args.start, "start"))
    end = duration if args.end is None else finite(args.end, "end")
    if end <= start or end > duration:
        raise ValueError("interval must be inside the video duration")
    first = int(round(start * fps))
    last = min(total, int(round(end * fps)))
    if last - first < 2:
        raise ValueError("interval is too short to track")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".blur-censor-", dir=args.output.parent) as temp_name:
        temp = Path(temp_name)
        frames_dir = temp / "frames"
        mask_dir = temp / "masks"
        out_dir = temp / "rendered"
        frames_dir.mkdir()
        mask_dir.mkdir()
        out_dir.mkdir()

        run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(args.input),
             "-vf", f"trim=start_frame={first}:end_frame={last},setpts=PTS-STARTPTS",
             "-fps_mode", "passthrough", str(frames_dir / "%06d.png")])
        frame_paths = sorted(frames_dir.glob("*.png"))
        if len(frame_paths) != last - first:
            raise ValueError(f"expected {last - first} frames, decoded {len(frame_paths)}")

        reference = args.reference_frame
        if reference < 0:
            reference = len(frame_paths) // 2
        reference = max(0, min(len(frame_paths) - 1, reference))

        if args.seed:
            hue = tuple(int(v) for v in parse_pair(args.hue, "hue"))
            sat = tuple(int(v) for v in parse_pair(args.sat, "sat"))
            val = tuple(int(v) for v in parse_pair(args.val, "val"))
            seeds = [parse_pair(s, "--seed") for s in args.seed]
            band = None
            if args.band:
                band = tuple(int(v) for v in parse_pair(args.band, "--band"))
            elif len(seeds) == 2:
                low = min(seeds[0][0], seeds[1][0])
                high = max(seeds[0][0], seeds[1][0])
                gap = high - low
                band = (int(low + gap * 0.25), int(high - gap * 0.25))
            for index, path in enumerate(frame_paths):
                image = cv2.imread(str(path))
                cv2.imwrite(str(mask_dir / f"{index + 1:06d}.png"), skin_mask(image, hue, sat, val))
            mask_paths = sorted(mask_dir.glob("*.png"))
            min_area = args.min_area or max(400, int(0.0006 * width * height))
            tracks = [track_skin(mask_paths, reference, seed, band, width, height,
                                 margin=24, radius=50, min_area=min_area) for seed in seeds]
        else:
            rects = [parse_rect(r, "--region") for r in args.region]
            tracks = [track_template(frame_paths, reference,
                                     (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2),
                                     (int(rect[2]), int(rect[3])), radius=args.search_radius,
                                     pad=args.track_pad, min_score=args.min_score)
                      for rect in rects]

        smoothed = [smooth_track(track, args.smooth) for track in tracks]

        for index, path in enumerate(frame_paths):
            image = cv2.imread(str(path))
            out = image.astype(np.float32)
            for boxes in smoothed:
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
            if args.core > 0:
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
            cv2.imwrite(str(out_dir / f"{index + 1:06d}.png"), out)

        chains, labels = [], []
        index = 0
        if first > 0:
            chains.append(f"[0:v]trim=start_frame=0:end_frame={first},setpts=PTS-STARTPTS[c{index}]")
            labels.append(f"[c{index}]")
            index += 1
        chains.append(f"[1:v]setpts=PTS-STARTPTS[c{index}]")
        labels.append(f"[c{index}]")
        index += 1
        if last < total:
            chains.append(f"[0:v]trim=start_frame={last},setpts=PTS-STARTPTS[c{index}]")
            labels.append(f"[c{index}]")
        graph = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1[v]"

        staged = temp / "render.mp4"
        run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(args.input), "-framerate", f"{fps:.12g}", "-i", str(out_dir / "%06d.png"),
             "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", args.audio, "-movflags", "+faststart", str(staged)])
        rendered = probe(args.ffprobe, staged)
        if not any(s.get("codec_type") == "video" for s in rendered.get("streams", [])):
            raise ValueError("rendered output has no video stream")
        os.replace(staged, args.output)

    print(json.dumps({
        "output": str(args.output.resolve()),
        "input": str(args.input.resolve()),
        "interval": [start, end],
        "frames": [first, last],
        "referenceFrame": reference,
        "videoFPS": fps,
        "videoSize": [width, height],
        "regions": len(smoothed),
        "mode": "skin-seed" if args.seed else "template-rect",
        "blurFraction": args.blur,
        "audioMode": args.audio,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"error: {detail}", file=sys.stderr)
        raise SystemExit(2)
