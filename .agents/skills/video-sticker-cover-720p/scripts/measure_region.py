#!/usr/bin/env python3
"""Measure a static sticker rectangle inside a search region using temporal variance."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

PRESENCE_THRESHOLD = 12.0
GRADIENT_MIN = 10.0
EDGE_BAND = 0.35


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def probe(ffprobe: str, path: Path) -> dict:
    result = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                             "format=duration:stream=codec_type,width,height,avg_frame_rate",
                             "-of", "json", str(path)],
                            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.loads(result.stdout)


def parse_region(value: str) -> tuple[int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must be X,Y,W,H")
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("region must be X,Y,W,H with integer values") from exc


def parse_frames(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("frames must be FIRST:LAST")
    try:
        first, last = (int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("frames must be integers") from exc
    if first < 0 or last < first:
        raise argparse.ArgumentTypeError("frames must satisfy 0 <= FIRST <= LAST")
    return first, last


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--region", type=parse_region, required=True,
                        help="search window X,Y,W,H around the sticker, including background margin")
    parser.add_argument("--frames", type=parse_frames,
                        help="frame range FIRST:LAST to analyse; defaults to the whole clip")
    parser.add_argument("--work-dir", type=Path,
                        help="directory for the decoded PNG frames; defaults to a fresh system temp dir")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser.parse_args()


def spans(indices: list[int]) -> list[list[int]]:
    if not indices:
        return []
    out = [[indices[0], indices[0]]]
    for value in indices[1:]:
        if value == out[-1][1] + 1:
            out[-1][1] = value
        else:
            out.append([value, value])
    return out


def gradient_edge(values: np.ndarray, side: str, origin: int, offset: int) -> tuple[int, float]:
    """Find the strongest luminance step in the outer band of the profile.

    Returns the edge coordinate in source pixels plus the step magnitude. `side="start"` searches
    the leading band and returns the first pixel after the step; `side="stop"` searches the
    trailing band and returns the last pixel before it.
    """
    length = len(values)
    band = max(2, int(length * EDGE_BAND))
    if side == "start":
        span = range(0, min(band, length))
    else:
        span = range(length - 1, max(-1, length - 1 - band), -1)
    best = max(span, key=lambda i: values[i])
    return origin + best + offset, float(values[best])


def window(values: np.ndarray, index: int, origin: int, pad: int = 10) -> list[list[float]]:
    lo = max(0, index - pad)
    hi = min(len(values), index + pad + 1)
    return [[int(origin + i), round(float(values[i]), 2)] for i in range(lo, hi)]


def scan_edge(values: np.ndarray, center: int, threshold: float, forward: bool) -> int | None:
    """Return the first index past the sticker core where variance leaves the sticker level."""
    if forward:
        for index in range(center, len(values) - 1):
            if values[index + 1] >= threshold:
                return index
    else:
        for index in range(center, 0, -1):
            if values[index - 1] >= threshold:
                return index
    return None


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise ValueError(f"input file not found: {args.input}")

    media = probe(args.ffprobe, args.input)
    video = next((s for s in media.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("input has no video stream")
    frame_w, frame_h = int(video["width"]), int(video["height"])
    x0, y0, region_w, region_h = args.region
    if x0 < 0 or y0 < 0 or region_w <= 0 or region_h <= 0:
        raise ValueError("region origin must be non-negative and size must be positive")
    if x0 + region_w > frame_w or y0 + region_h > frame_h:
        raise ValueError("region is outside the video dimensions")

    if args.work_dir is not None:
        work_dir = args.work_dir.resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        if any(work_dir.glob("f_*.png")):
            raise ValueError(f"work directory already holds decoded frames: {work_dir}")
        temp_dir = work_dir
        owned = False
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="sticker-measure-"))
        owned = True
    try:
        run([args.ffmpeg, "-hide_banner", "-loglevel", "error",
             "-i", str(args.input), "-fps_mode", "passthrough", "-y",
             str(temp_dir / "f_%04d.png")])
        decoded = sorted(temp_dir.glob("f_*.png"))
        if not decoded:
            raise ValueError("no frames decoded")
        first, last = (0, len(decoded) - 1) if args.frames is None else args.frames
        if last >= len(decoded):
            raise ValueError(f"frame range exceeds the decoded frame count {len(decoded)}")
        files = decoded[first:last + 1]

        def load_crop(path: Path) -> np.ndarray:
            frame = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
            return frame[y0:y0 + region_h, x0:x0 + region_w]

        reference_index = len(files) // 2
        reference = load_crop(files[reference_index])
        sums = np.zeros((region_h, region_w, 3), dtype=np.float64)
        sums_sq = np.zeros((region_h, region_w, 3), dtype=np.float64)
        for path in files:
            frame = load_crop(path)
            sums += frame
            sums_sq += frame.astype(np.float64) ** 2

        count = len(files)
        mean_frame = (sums / count).astype(np.float32)
        spread = np.sqrt(np.maximum(sums_sq / count - (sums / count) ** 2, 0.0)).mean(axis=2)

        inset_y, inset_x = max(1, region_h // 5), max(1, region_w // 5)
        sticker_level = float(np.median(spread[inset_y:region_h - inset_y, inset_x:region_w - inset_x]))
        border = max(1, min(region_h, region_w) // 12)
        ring = np.concatenate([spread[:border].ravel(), spread[-border:].ravel(),
                               spread[:, :border].ravel(), spread[:, -border:].ravel()])
        background_level = float(np.median(ring))
        if background_level - sticker_level < 3.0:
            raise ValueError(
                "no static rectangle found: the region centre is not calmer than its border. "
                f"sticker={sticker_level:.2f} background={background_level:.2f}. "
                "Widen the region so it includes moving background around a fixed sticker, "
                "or the overlay may be animated and this fixed-rectangle approach does not apply."
            )
        threshold = (sticker_level + background_level) / 2

        row_values = spread[:, inset_x:region_w - inset_x].mean(axis=1)
        col_values = spread[inset_y:region_h - inset_y, :].mean(axis=0)
        center_row, center_col = region_h // 2, region_w // 2

        top_index = scan_edge(row_values, center_row, threshold, forward=False)
        bottom_index = scan_edge(row_values, center_row, threshold, forward=True)
        left_index = scan_edge(col_values, center_col, threshold, forward=False)
        right_index = scan_edge(col_values, center_col, threshold, forward=True)
        top = y0 + (top_index if top_index is not None else 0)
        bottom = y0 + (bottom_index if bottom_index is not None else region_h - 1)
        left = x0 + (left_index if left_index is not None else 0)
        right = x0 + (right_index if right_index is not None else region_w - 1)

        grad_rows = np.abs(np.diff(mean_frame.mean(axis=2), axis=0)).mean(axis=1)
        grad_cols = np.abs(np.diff(mean_frame.mean(axis=2), axis=1)).mean(axis=0)
        g_top, s_top = gradient_edge(grad_rows, "start", y0, 1)
        g_bottom, s_bottom = gradient_edge(grad_rows, "stop", y0, 0)
        g_left, s_left = gradient_edge(grad_cols, "start", x0, 1)
        g_right, s_right = gradient_edge(grad_cols, "stop", x0, 0)
        gradient_rect = None
        if min(s_top, s_bottom, s_left, s_right) >= GRADIENT_MIN:
            gradient_rect = {"x": int(g_left), "y": int(g_top),
                             "width": int(max(1, g_right - g_left + 1)),
                             "height": int(max(1, g_bottom - g_top + 1))}
        variance_rect = {"x": int(left), "y": int(top),
                         "width": int(max(1, right - left + 1)),
                         "height": int(max(1, bottom - top + 1))}
        # An animated inner image defeats the variance crossing, so a confident hard edge wins
        chosen = gradient_rect or variance_rect

        # Presence is judged on a ring just inside the chosen rect: a fixed card keeps its border
        # still even when the artwork inside moves.
        ring_thickness = max(2, min(chosen["width"], chosen["height"]) // 40)
        rx0, ry0 = chosen["x"] - x0, chosen["y"] - y0
        rx1, ry1 = rx0 + chosen["width"], ry0 + chosen["height"]
        ring_mask = np.zeros((region_h, region_w), dtype=bool)
        ring_mask[max(0, ry0):ry1, max(0, rx0):rx1] = True
        ring_mask[max(0, ry0 + ring_thickness):ry1 - ring_thickness,
                  max(0, rx0 + ring_thickness):rx1 - ring_thickness] = False
        reference_ring = reference[ring_mask]
        presence_diffs: list[float] = []
        for path in files:
            if path == files[reference_index]:
                presence_diffs.append(0.0)
                continue
            frame = load_crop(path)
            presence_diffs.append(float(np.abs(frame[ring_mask] - reference_ring).mean()))

        present = [first + i for i, value in enumerate(presence_diffs) if value < PRESENCE_THRESHOLD]
        result = {
            "input": str(args.input.resolve()),
            "frameSize": [frame_w, frame_h],
            "decodedFrames": len(decoded),
            "analysedFrames": {"first": first, "last": last, "count": count},
            "region": {"x": x0, "y": y0, "width": region_w, "height": region_h},
            "levels": {"sticker": round(sticker_level, 2),
                       "background": round(background_level, 2),
                       "threshold": round(threshold, 2)},
            "rects": {
                "variance": variance_rect,
                "gradient": gradient_rect,
                "gradientStrengths": {"top": round(s_top, 1), "bottom": round(s_bottom, 1),
                                      "left": round(s_left, 1), "right": round(s_right, 1)},
            },
            "suggestedRect": chosen,
            "edges": {"top": int(top), "bottom": int(bottom), "left": int(left), "right": int(right)},
            "presence": spans(present),
            "evidence": {
                "rowProfile": window(row_values, top_index if top_index is not None else 0, y0)
                + window(row_values, bottom_index if bottom_index is not None else region_h - 1, y0),
                "colProfile": window(col_values, left_index if left_index is not None else 0, x0)
                + window(col_values, right_index if right_index is not None else region_w - 1, x0),
                "gradientPeakRows": [[int(y0 + int(i)), round(float(grad_rows[i]), 1)]
                                     for i in np.argsort(-grad_rows)[:8]],
                "gradientPeakCols": [[int(x0 + int(i)), round(float(grad_cols[i]), 1)]
                                     for i in np.argsort(-grad_cols)[:8]],
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if owned:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
