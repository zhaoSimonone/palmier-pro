#!/usr/bin/env python3
"""Cover a fixed source-video rectangle with an opaque neutral color."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def finite(value: str | float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def probe(ffprobe: str, path: Path) -> dict:
    result = run([
        ffprobe, "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,duration,avg_frame_rate",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def parse_color(value: str) -> str:
    parts = value.split(",")
    if len(parts) != 3:
        raise ValueError("color must be R,G,B")
    channels = []
    for part in parts:
        channel = int(part)
        if channel < 0 or channel > 255:
            raise ValueError("color channels must be between 0 and 255")
        channels.append(channel)
    return "0x{:02x}{:02x}{:02x}".format(*channels)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--color", default="58,58,58")
    parser.add_argument("--audio", choices=("copy", "aac"), default="copy")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise ValueError(f"input file not found: {args.input}")
    if args.output.resolve() == args.input.resolve():
        raise ValueError("output must differ from input")
    if args.output.exists():
        raise ValueError(f"output already exists: {args.output}")
    if args.output.suffix.lower() != ".mp4":
        raise ValueError("output must be an MP4 file")
    if args.x < 0 or args.y < 0 or args.width <= 0 or args.height <= 0:
        raise ValueError("x and y must be non-negative; width and height must be positive")

    media = probe(args.ffprobe, args.input)
    video = next((item for item in media.get("streams", []) if item.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("input has no video stream")
    video_width = int(video["width"])
    video_height = int(video["height"])
    video_duration = finite(video.get("duration") or media.get("format", {}).get("duration"), "video duration")
    if args.x + args.width > video_width or args.y + args.height > video_height:
        raise ValueError("cover rectangle is outside the video dimensions")
    start = finite(args.start, "start")
    end = video_duration if args.end is None else finite(args.end, "end")
    if start < 0 or end <= start or end > video_duration:
        raise ValueError("cover interval must be within the video duration")
    color = parse_color(args.color)

    fps = video.get("avg_frame_rate") or ""
    filter_expr = (
        f"drawbox=x={args.x}:y={args.y}:w={args.width}:h={args.height}:"
        f"color={color}@1.0:t=fill:enable='between(t,{start:.12g},{end:.12g})'"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".exact-sticker-cover-", dir=args.output.parent) as temp_dir:
        staged = Path(temp_dir) / "render.mp4"
        command = [
            args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(args.input),
            "-vf", filter_expr,
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", args.audio,
            "-t", f"{video_duration:.12g}", "-movflags", "+faststart",
            str(staged),
        ]
        run(command)
        rendered = probe(args.ffprobe, staged)
        if not any(item.get("codec_type") == "video" for item in rendered.get("streams", [])):
            raise ValueError("rendered output has no video stream")
        try:
            os.link(staged, args.output)
        except FileExistsError as exc:
            raise ValueError(f"output already exists: {args.output}") from exc

    print(json.dumps({
        "input": str(args.input.resolve()),
        "output": str(args.output.resolve()),
        "videoSize": [video_width, video_height],
        "region": {"x": args.x, "y": args.y, "width": args.width, "height": args.height},
        "start": start,
        "end": end,
        "color": args.color,
        "audioMode": args.audio,
        "videoFPS": fps,
        "duration": video_duration,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2)
