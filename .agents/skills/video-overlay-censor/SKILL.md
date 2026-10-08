---
name: video-overlay-censor
description: Apply a user-provided animated GIF or PNG as a fixed-size censor/cover overlay on a video, with fixed or keyframed position, edge-background cleanup, audio preservation, and sampled-frame verification. Use for explicit user-directed coverage of a logo, watermark, face, sensitive area, or object; do not use for automatic sensitive-content detection.
---

# GIF Video Overlay Censor

Use this skill for deterministic, user-directed video masking with an image or animated GIF. It supports fixed placement and manual keyframe tracking while keeping overlay geometry stable.

## Capabilities

- Inspect video and overlay duration, dimensions, frame rate, codecs, audio, GIF frame timing, and loop behavior with `ffprobe`.
- Decode GIF frames with Pillow/OpenCV and loop them through an active interval.
- Remove only edge-connected near-white background pixels, preserving enclosed white artwork.
- Render a fixed width and height, or preserve aspect ratio when height is omitted.
- Place the overlay at a fixed center or interpolate manually supplied `(time, x, y)` center keyframes.
- Composite RGBA overlay frames with FFmpeg and preserve audio by stream copy or explicit AAC encoding.
- Stage output beside the destination and refuse same-path or accidental overwrite.
- Verify output metadata and sample frames at the start, middle, motion turns, and end.

## Workflow

1. Confirm the exact input video, overlay asset, active time range, and whether placement is fixed or tracked. A screenshot or red box is visual guidance, not a machine-readable mask.
2. Inspect both assets with `ffprobe`. Do not assume 30 fps, a transparent GIF, or any particular canvas ratio.
3. Choose geometry explicitly. Coordinates are source-video pixels with top-left origin; `x/y` are overlay center coordinates. Use constant width and height unless the user explicitly requests scaling.
4. For a GIF with a plain white background, pass `--remove-edge-white`. This removes only near-white pixels connected to the frame edge; do not globally remove white.
5. Run `scripts/apply_overlay.py`. Use `--keyframes` for movement and add enough keys for hand occlusions, cuts, rapid turns, and end-of-shot movement. The script loops GIF frames and smooths position only, never size.
6. Verify the result with `ffprobe` and sampled frames. Check the first active frame, last active frame, every transition, fast motion, black/blank endings, and frames after the overlay ends. Confirm that the target is covered without unnecessary adjacent coverage.

## Keyframes

```json
{
  "keyframes": [
    {"time": 3.45, "x": 520, "y": 875},
    {"time": 5.20, "x": 410, "y": 835},
    {"time": 7.60, "x": 285, "y": 860},
    {"time": 8.29, "x": 350, "y": 835}
  ]
}
```

Keyframe times must be strictly increasing and cover the complete active interval. The active interval is half-open: the overlay is rendered for `start <= time < end`, so use the first frame after the target disappears or a cut/black frame as the end boundary.

## Command

```bash
python3 /path/to/skills/video-overlay-censor/scripts/apply_overlay.py \
  --input /path/to/input.mp4 \
  --overlay /path/to/cover.gif \
  --output /path/to/output.mp4 \
  --start 3.45 --end 8.29 \
  --width 270 --height 190 \
  --keyframes /tmp/overlay-keyframes.json \
  --remove-edge-white \
  --ffmpeg /opt/homebrew/bin/ffmpeg \
  --ffprobe /opt/homebrew/bin/ffprobe
```

For a fixed position, omit `--keyframes` and provide `--x` and `--y`. Use `--audio aac` when the source audio cannot be stream-copied. The output must be a new `.mp4`; the script refuses to overwrite an existing path.

## Boundaries

- This is compositing, not automatic semantic detection or frame-perfect segmentation. The user or another detector must provide placement.
- Never silently crop, retarget, resize, replace, or overwrite user media.
- Preserve the original video and report any geometry or audio adjustment.
- Do not treat a successful FFmpeg exit as sufficient: inspect metadata and sampled frames.

## Setup and verification

Create a Python virtual environment and install `requirements.txt` from this skill directory. FFmpeg and ffprobe are external executables; locate installed binaries with `command -v`, or pass their actual paths. Do not assume a particular Homebrew version exists.

Run `python3 -m unittest discover -s /path/to/skills/video-overlay-censor/tests -v`. Integration tests use synthetic assets only; set `FFMPEG` and `FFPROBE` if the executables are not on PATH.

## Coverage and limitations

- Read [implementation-notes.md](references/implementation-notes.md) for the coverage checks learned from previous edits.
- Transparent GIF holes and changing silhouettes are not opaque coverage. Check all GIF frames over the entire target, including wing tips and text edges. Preserve the original opaque background when needed, or agree on an opaque backing; do not claim that a transparent sticker guarantees concealment.
- Only CFR, unrotated SDR video is validated by this helper. VFR timing, rotation, HDR/color metadata, and subtitle/data-track preservation are not implemented. Inspect these before use and report unsupported inputs instead of promising lossless preservation.
- Rendering creates full-canvas PNG frames in a temporary directory on the destination volume; use short clips and check disk capacity. It is not a long-form streaming renderer.
- The helper processes one interval and one overlay per render. For multiple regions, plan all intervals first; repeated encoding degrades quality. Do not present it as an automatic multi-region tracking engine.
- This is an external file workflow, not a Palmier timeline/undo/MCP integration. Never write directly into a live `.palmier` package.
