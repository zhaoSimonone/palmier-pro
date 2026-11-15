#!/usr/bin/env python3
"""Cover fixed source-video rectangles and optionally export a scaled MP4 in one encode."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def probe(ffprobe: str, path: Path) -> dict:
    result = run([
        ffprobe, "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,duration,avg_frame_rate",
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


def parse_rate(value: str) -> float:
    numerator, _, denominator = str(value).partition("/")
    try:
        rate = float(numerator) / float(denominator or 1)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"frame rate must be a rational number: {value}") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError(f"frame rate must be positive: {value}")
    return rate


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


def parse_rect(value: str) -> dict:
    """Parse X,Y,W,H with an optional @START,END window override."""
    body, _, window = value.partition("@")
    parts = body.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect must be X,Y,W,H or X,Y,W,H@START,END")
    try:
        x, y, width, height = (int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rect must be X,Y,W,H with integer values") from exc
    rect = {"x": x, "y": y, "width": width, "height": height}
    if window:
        bounds = window.split(",")
        if len(bounds) != 2:
            raise argparse.ArgumentTypeError("rect window must be @START,END")
        try:
            rect["start"], rect["end"] = (float(bound) for bound in bounds)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("rect window bounds must be numbers") from exc
    return rect


def parse_size(value: str) -> tuple[int, int]:
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("size must be WxH, for example 720x1280")
    try:
        width, height = (int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must be WxH with integer values") from exc
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise argparse.ArgumentTypeError("size must be positive even numbers")
    return width, height


def frame_bounds(start: float, end: float, rate: float) -> tuple[int, int]:
    """Convert a half-open time interval to inclusive frame indices."""
    def snap(value: float) -> float:
        nearest = round(value)
        return nearest if abs(value - nearest) < 1e-4 else value

    return math.ceil(snap(start * rate)), math.ceil(snap(end * rate)) - 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rect", type=parse_rect, action="append", required=True,
                        metavar="X,Y,W,H[@START,END]",
                        help="source-pixel rectangle to cover; repeat for multiple regions")
    parser.add_argument("--size", type=parse_size,
                        help="export size WxH applied after covering, for example 720x1280")
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

    media = probe(args.ffprobe, args.input)
    video = next((item for item in media.get("streams", []) if item.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("input has no video stream")
    video_width = int(video["width"])
    video_height = int(video["height"])
    video_duration = finite(video.get("duration") or media.get("format", {}).get("duration"), "video duration")

    start = finite(args.start, "start")
    end = video_duration if args.end is None else finite(args.end, "end")
    if start < 0 or end <= start or end > video_duration:
        raise ValueError("cover interval must be within the video duration")
    frame_rate = parse_rate(video.get("avg_frame_rate") or "")

    regions = []
    for rect in args.rect:
        rect_start = finite(rect.get("start", start), "rect start")
        rect_end = finite(rect.get("end", end), "rect end")
        if rect_start < 0 or rect_end <= rect_start or rect_end > video_duration:
            raise ValueError("rect window must be within the video duration")
        first, last = frame_bounds(rect_start, rect_end, frame_rate)
        if last < first:
            raise ValueError("rect window selects no frames")
        x, y, width, height = rect["x"], rect["y"], rect["width"], rect["height"]
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("rect origin must be non-negative and size must be positive")
        if x + width > video_width or y + height > video_height:
            raise ValueError("cover rectangle is outside the video dimensions")
        regions.append({
            "x": x, "y": y, "width": width, "height": height,
            "firstFrame": first, "lastFrame": last,
        })

    color = parse_color(args.color)
    filters = [
        f"drawbox=x={region['x']}:y={region['y']}:w={region['width']}:h={region['height']}:"
        f"color={color}@1.0:t=fill:"
        f"enable='between(n,{region['firstFrame']},{region['lastFrame']})'"
        for region in regions
    ]
    if args.size:
        filters.append(f"scale={args.size[0]}:{args.size[1]}:flags=lanczos")
    filter_expr = ",".join(filters)

    record = next((item for item in media.get("streams", []) if item.get("codec_type") == "audio"), None)
    audio_duration = finite(record.get("duration"), "audio duration") if record and record.get("duration") else None
    # Trimming with -t can drop the last video frames, so trim overlong audio instead and
    # leave the video stream complete.
    audio_filter = None
    if audio_duration is not None and audio_duration > video_duration + 1e-3:
        audio_filter = f"atrim=0:{video_duration:.12g}"

    output_size = list(args.size) if args.size else [video_width, video_height]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sticker-cover-", dir=args.output.parent) as temp_dir:
        staged = Path(temp_dir) / "render.mp4"
        command = [
            args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(args.input),
            "-vf", filter_expr,
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
        ]
        if audio_filter:
            # A filter cannot run alongside stream copy, so this path re-encodes audio.
            command += ["-af", audio_filter, "-c:a", "aac", "-b:a", "192k"]
        else:
            command += ["-c:a", args.audio]
        command += ["-movflags", "+faststart", str(staged)]
        run(command)
        rendered = probe(args.ffprobe, staged)
        rendered_video = next((item for item in rendered.get("streams", [])
                               if item.get("codec_type") == "video"), None)
        if rendered_video is None:
            raise ValueError("rendered output has no video stream")
        if (int(rendered_video["width"]), int(rendered_video["height"])) != tuple(output_size):
            raise ValueError("rendered output size does not match the requested size")
        try:
            os.link(staged, args.output)
        except FileExistsError as exc:
            raise ValueError(f"output already exists: {args.output}") from exc

    print(json.dumps({
        "input": str(args.input.resolve()),
        "output": str(args.output.resolve()),
        "sourceSize": [video_width, video_height],
        "outputSize": output_size,
        "regions": regions,
        "start": start,
        "end": end,
        "color": args.color,
        "audioMode": args.audio,
        "videoFPS": video.get("avg_frame_rate") or "",
        "duration": video_duration,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
