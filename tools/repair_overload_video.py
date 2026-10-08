#!/usr/bin/env python3
"""Build a reference copy of the supplied clip using its unobscured tail as a donor."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def feather_mask(width: int, height: int, left: int, top: int, right: int, bottom: int, feather: int) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    pixels = np.zeros((height, width), dtype=np.uint8)
    pixels[top:bottom, left:right] = 255
    if feather:
        mask = Image.fromarray(pixels, "L").filter(ImageFilter.GaussianBlur(feather))
    else:
        mask = Image.fromarray(pixels, "L")
    return mask


def remove_overlay_band(frame: Image.Image, y0: int, y1: int) -> Image.Image:
    """Replace the fixed title band by a smooth continuation of the torso."""
    arr = np.asarray(frame).copy()
    height = y1 - y0
    upper = arr[y0 - 10]
    lower = arr[y1 + 10]
    for offset in range(height):
        weight = (offset + 1) / (height + 1)
        arr[y0 + offset] = ((1.0 - weight) * upper + weight * lower).astype(np.uint8)
    return Image.fromarray(arr)


def soften_region(frame: Image.Image, box: tuple[int, int, int, int], radius: int = 10) -> Image.Image:
    x0, y0, x1, y1 = box
    blurred = frame.crop(box).filter(ImageFilter.GaussianBlur(radius))
    result = frame.copy()
    result.paste(blurred, box)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()

    frames_dir = args.work / "frames"
    clean_dir = args.work / "clean"
    frames_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)
    run([
        "/opt/homebrew/Cellar/ffmpeg/9.0.1/bin/ffmpeg", "-y", "-i", str(args.source),
        "-fps_mode", "passthrough", str(frames_dir / "%05d.png"),
    ])

    paths = sorted(frames_dir.glob("*.png"))
    if not paths:
        raise RuntimeError("source produced no frames")
    first = Image.open(paths[0]).convert("RGB")
    width, height = first.size

    # The source reveals a clean skirt after about 6 seconds. Keep one sharp donor
    # frame so the reconstruction does not acquire temporal ghosting.
    donor = Image.open(paths[min(145, len(paths) - 1)]).convert("RGB")
    donor = soften_region(donor, (270, 1020, 450, 1145), 9)
    donor_patch = donor.crop((140, 890, 580, height))

    panel_mask = feather_mask(width, height, 180, 905, 540, height, 18)

    for index, path in enumerate(paths, start=1):
        frame = Image.open(path).convert("RGB")
        # Remove the fixed title without affecting the rest of the upper body.
        frame = remove_overlay_band(frame, 835, 900)

        # The anime card is opaque only in the first part of the clip. Composite
        # the real skirt from the unobscured tail and feather the side joins.
        if index < 145:
            canvas = frame.copy()
            canvas.paste(donor_patch, (140, 890))
            frame = Image.composite(canvas, frame, panel_mask)

        # Small fixed watermark and countdown digits are not useful as references.
        frame = soften_region(frame, (20, 1015, 155, 1125), 14)
        frame = soften_region(frame, (270, 1020, 450, 1145), 9)
        frame.save(clean_dir / f"{index:05d}.png", compress_level=1)

    run([
        "/opt/homebrew/Cellar/ffmpeg/9.0.1/bin/ffmpeg", "-y", "-framerate", "24", "-i",
        str(clean_dir / "%05d.png"), "-i", str(args.source), "-map", "0:v:0", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(args.output),
    ])


if __name__ == "__main__":
    main()
