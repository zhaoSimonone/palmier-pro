---
name: video-exact-sticker-cover
description: Cover a fixed rectangular sticker, watermark, or logo in a video with an opaque region that matches the sticker bounds exactly. Use when the user wants the source sticker fully hidden with no extra surrounding coverage; do not use for moving objects, faces, or red-box annotations as masks.
---

# Video Exact Sticker Cover

Use this skill when a visible sticker or watermark is fixed in the source video and must be covered at its own pixel bounds. The output must hide the complete sticker while preserving adjacent pixels. A user-drawn red box, screenshot, or preview guide is visual reference only and must never become the output mask unless it is confirmed to match the source sticker boundary.

## Workflow

1. Resolve the exact source video from the user request. Never use an earlier rendered output as the source, and never overwrite the source or an existing output.
2. Probe the source with `ffprobe`. Confirm a supported constant-frame-rate, unrotated SDR video, its dimensions, video duration, and audio presence.
3. Extract representative frames from the original source at the beginning, middle, motion changes, and end. Measure the sticker's own hard rectangular edges in source-video pixels. Verify that the same `(x, y, width, height)` is valid across the sampled frames before rendering.
4. Ignore red boxes and other annotation graphics when choosing the region. The region uses top-left origin and must satisfy `0 <= x`, `0 <= y`, `x + width <= videoWidth`, and `y + height <= videoHeight`.
5. Run `scripts/apply_exact_sticker_cover.py` with the measured region. The script draws an opaque neutral cover only inside that rectangle for the requested interval. It does not add a red guide, padding, blur halo, or safety margin.
6. Verify the rendered metadata and inspect sampled output frames. For a fixed sticker, verify every decoded frame when the clip is short enough. Confirm that no sticker pixels remain and that the cover does not extend past the measured source rectangle.
7. Report the exact source path, output path, measured rectangle, active interval, audio handling, and any unsupported media properties.

## Command

```bash
python3 /path/to/video-exact-sticker-cover/scripts/apply_exact_sticker_cover.py \
  --input /path/to/source.mp4 \
  --output /path/to/source-exact-cover.mp4 \
  --x 256 --y 1261 --width 568 --height 588 \
  --start 0 --end 8.333333 \
  --color 58,58,58 \
  --ffmpeg /opt/homebrew/bin/ffmpeg \
  --ffprobe /opt/homebrew/bin/ffprobe
```

`--end` is exclusive at the video-frame boundary. Omit it to cover through the video stream duration. The script trims an overlong audio stream to the video duration and preserves audio with stream copy when possible; use `--audio aac` when copying fails.

## Geometry rules

- Coordinates are source-video pixels, not screenshot pixels.
- Use the sticker's measured outer edge. Do not add coverage for a red annotation, nearby clothing, hands, or background.
- If the sticker boundary changes, this fixed-rectangle skill does not apply. Use keyframed tracking or a shape mask and state that the exact fixed-rectangle workflow was not used.
- If the source is VFR, rotated, HDR, or has an unsupported data track, stop before rendering and report the limitation.

## Boundaries

This skill performs deterministic rectangular compositing. It does not infer copyright ownership, identify sensitive content, track arbitrary objects, remove a sticker by inpainting, or guarantee that a platform will approve unrelated content. The original source remains untouched.
