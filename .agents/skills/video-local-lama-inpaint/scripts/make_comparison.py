#!/usr/bin/env python3
"""Create a synchronized original-left/repaired-right comparison video."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--repaired", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--crf", default="18")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        "[0:v]setpts=PTS-STARTPTS,setsar=1,"
        "scale=-2:720:flags=lanczos[left];"
        "[1:v]setpts=PTS-STARTPTS,setsar=1,"
        "scale=-2:720:flags=lanczos[right];"
        "[left][right]hstack=inputs=2:shortest=1[v]"
    )
    command = [
        args.ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(args.original),
        "-i",
        str(args.repaired),
        "-filter_complex",
        filter_graph,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-crf",
        args.crf,
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-shortest",
        str(args.output),
    ]
    run(command)


if __name__ == "__main__":
    main()
