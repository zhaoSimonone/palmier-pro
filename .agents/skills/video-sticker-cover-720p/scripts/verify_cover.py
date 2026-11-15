#!/usr/bin/env python3
"""Verify that covered rectangles are flat, that no sticker fringe survives, and that the rest is intact."""
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


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def probe(ffprobe: str, path: Path) -> dict:
    result = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                             "stream=codec_type,width,height,nb_frames,duration:format=duration",
                             "-of", "json", str(path)],
                            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.loads(result.stdout)


def parse_rect(value: str) -> tuple[int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect must be X,Y,W,H")
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rect must be X,Y,W,H with integer values") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="rendered MP4 to verify")
    parser.add_argument("--source", type=Path, required=True, help="original MP4 that was covered")
    parser.add_argument("--rect", type=parse_rect, action="append", required=True,
                        metavar="X,Y,W,H", help="covered rectangle in the output's pixel space; repeat per region")
    parser.add_argument("--color", default="58,58,58", help="requested cover colour, R,G,B")
    parser.add_argument("--work-dir", type=Path,
                        help="directory for decoded frames; defaults to a fresh system temp dir")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser.parse_args()


def decode(ffmpeg: str, source: Path, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
         "-fps_mode", "passthrough", "-y", str(target / "f_%04d.png")])
    return sorted(target.glob("f_*.png"))


def main() -> int:
    args = parse_args()
    if not args.output.is_file():
        raise ValueError(f"output file not found: {args.output}")
    if not args.source.is_file():
        raise ValueError(f"source file not found: {args.source}")
    expected = [int(part) for part in args.color.split(",")]
    if len(expected) != 3:
        raise ValueError("color must be R,G,B")

    out_media = probe(args.ffprobe, args.output)
    src_media = probe(args.ffprobe, args.source)
    out_video = next((s for s in out_media.get("streams", []) if s.get("codec_type") == "video"), None)
    src_video = next((s for s in src_media.get("streams", []) if s.get("codec_type") == "video"), None)
    if out_video is None or src_video is None:
        raise ValueError("both files need a video stream")
    out_w, out_h = int(out_video["width"]), int(out_video["height"])
    src_w, src_h = int(src_video["width"]), int(src_video["height"])
    out_audio = any(s.get("codec_type") == "audio" for s in out_media.get("streams", []))
    src_audio = any(s.get("codec_type") == "audio" for s in src_media.get("streams", []))

    issues: list[str] = []
    for x, y, w, h in args.rect:
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > out_w or y + h > out_h:
            raise ValueError(f"rect {x},{y},{w},{h} is outside the {out_w}x{out_h} output")

    if args.work_dir is not None:
        work = args.work_dir.resolve()
        work.mkdir(parents=True, exist_ok=True)
        owned = False
    else:
        work = Path(tempfile.mkdtemp(prefix="sticker-verify-"))
        owned = True
    try:
        out_files = decode(args.ffmpeg, args.output, work / "out")
        src_files = decode(args.ffmpeg, args.source, work / "src")
        if len(out_files) != len(src_files):
            issues.append(f"frame count differs: output {len(out_files)} vs source {len(src_files)}")

        mask = np.ones((out_h, out_w), dtype=bool)
        for x, y, w, h in args.rect:
            mask[y:y + h, x:x + w] = False

        rect_stats = [{"mean": [], "std": [], "max": 0.0} for _ in args.rect]
        ring_sums = np.zeros((out_h, out_w, 3), dtype=np.float64)
        ring_sums_sq = np.zeros((out_h, out_w, 3), dtype=np.float64)
        ring_mask = np.zeros((out_h, out_w), dtype=bool)
        for x, y, w, h in args.rect:
            expand = 6
            outer = np.zeros((out_h, out_w), dtype=bool)
            outer[max(0, y - expand):min(out_h, y + h + expand), max(0, x - expand):min(out_w, x + w + expand)] = True
            outer[y:y + h, x:x + w] = False
            ring_mask |= outer

        outside_diffs: list[float] = []
        for index, path in enumerate(out_files):
            frame = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
            for slot, (x, y, w, h) in enumerate(args.rect):
                block = frame[y:y + h, x:x + w]
                rect_stats[slot]["mean"].append(float(block.mean()))
                rect_stats[slot]["std"].append(float(block.std()))
                rect_stats[slot]["max"] = max(rect_stats[slot]["max"], float(block.max()))
            ring_sums[ring_mask] += frame[ring_mask]
            ring_sums_sq[ring_mask] += frame[ring_mask].astype(np.float64) ** 2

            if index < len(src_files):
                source_frame = np.asarray(Image.open(src_files[index]).convert("RGB"), dtype=np.float32)
                if (src_w, src_h) != (out_w, out_h):
                    source_frame = np.asarray(
                        Image.open(src_files[index]).convert("RGB").resize((out_w, out_h), Image.LANCZOS),
                        dtype=np.float32)
                outside_diffs.append(float(np.abs(frame[mask] - source_frame[mask]).mean()))

        count = len(out_files)
        ring_spread = np.sqrt(np.maximum(ring_sums_sq / count - (ring_sums / count) ** 2, 0.0)).mean(axis=2)

        def mean_of(rows: slice, cols: slice) -> float:
            patch = ring_spread[rows, cols]
            return round(float(patch.mean()), 2) if patch.size else 0.0

        rings = []
        for x, y, w, h in args.rect:
            cols = slice(max(0, x - 6), min(out_w, x + w + 6))
            rings.append({
                "above": {"adjacent": mean_of(slice(max(0, y - 2), max(1, y)), cols),
                          "outer": mean_of(slice(max(0, y - 8), max(1, y - 4)), cols)},
                "below": {"adjacent": mean_of(slice(min(out_h, y + h), min(out_h, y + h + 2)), cols),
                          "outer": mean_of(slice(min(out_h, y + h + 4), min(out_h, y + h + 8)), cols)},
                "left": {"adjacent": mean_of(slice(max(0, y), y + h), slice(max(0, x - 2), max(1, x))),
                         "outer": mean_of(slice(max(0, y), y + h), slice(max(0, x - 8), max(1, x - 4)))},
                "right": {"adjacent": mean_of(slice(max(0, y), y + h), slice(min(out_w, x + w), min(out_w, x + w + 2))),
                          "outer": mean_of(slice(max(0, y), y + h), slice(min(out_w, x + w + 4), min(out_w, x + w + 8)))},
            })

        blocks = []
        for slot, (x, y, w, h) in enumerate(args.rect):
            stat = rect_stats[slot]
            mean_low, mean_high = min(stat["mean"]), max(stat["mean"])
            std_high = max(stat["std"])
            blocks.append({
                "rect": {"x": x, "y": y, "width": w, "height": h},
                "meanRange": [round(mean_low, 2), round(mean_high, 2)],
                "requested": expected,
                "stdMax": round(std_high, 2),
                "maxBrightness": round(stat["max"], 1),
            })
            if abs(mean_high - expected[0]) > 3.0 or std_high > 2.5:
                issues.append(f"rect {x},{y},{w},{h} is not flat: mean {mean_low:.2f}-{mean_high:.2f}, std {std_high:.2f}")

        outside = {"mean": round(float(np.mean(outside_diffs)), 3),
                   "max": round(float(np.max(outside_diffs)), 3)} if outside_diffs else None
        if outside and outside["mean"] > 3.0:
            issues.append("outside-region difference is large; confirm against a no-cover re-encode baseline")

        for rect_ring in rings:
            for side, pair in rect_ring.items():
                if pair["outer"] - pair["adjacent"] > max(4.0, 0.2 * max(pair["outer"], 1)):
                    issues.append(f"{side} ring dips from {pair['outer']} to {pair['adjacent']}; check for a leftover fringe")

        if not out_audio:
            issues.append("output has no audio while the source does" if src_audio else "output has no audio")
        if int(out_video.get("nb_frames") or count) != int(src_video.get("nb_frames") or len(src_files)):
            issues.append("frame count differs from the source")

        verdict = "pass" if not issues else "fail"
        print(json.dumps({
            "output": str(args.output.resolve()),
            "source": str(args.source.resolve()),
            "outputSize": [out_w, out_h],
            "sourceSize": [src_w, src_h],
            "frames": count,
            "blocks": blocks,
            "rings": rings,
            "outsideDiff": outside,
            "audio": {"output": out_audio, "source": src_audio},
            "verdict": verdict,
            "issues": issues,
        }, ensure_ascii=False, indent=2))
        return 0 if verdict == "pass" else 1
    finally:
        if owned:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
