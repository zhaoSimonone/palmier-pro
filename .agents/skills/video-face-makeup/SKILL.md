---
name: video-face-makeup
description: Apply a tracked face makeup look onto an existing video, especially 轻薄暖桃妆 (warm peach blush, coral lips, faint warmth). Use for blush, 红晕, 补妆, or beauty overlay on a finished clip without regenerating identity or costume. Do not use for hair/costume replacement, whole-frame LUT grading, or GIF/logo overlays.
---

# Video Face Makeup

Overlay a named makeup look onto an already-finished video by tracking the face. This does not regenerate identity, hair, or costume.

## Default look

The calibrated look from this workflow is **轻薄暖桃妆**.

- Display name: `轻薄暖桃妆`
- Machine id: `warm-peach`
- Aliases: `peach`, `暖桃妆`, `轻薄暖桃妆`

It restores thin warm peach makeup that identity/hair generation often washes out: apple blush, coral lip, faint lid, slight face warmth. Recipe: `references/looks.md`.

If the user does not name a look, use `warm-peach`. Do not invent a heavier makeup style.

## Workflow

1. Confirm the input video, look id, strength (default `1.0`), and a new output path. Never overwrite the source. Do not replace an existing output unless the user asked to replace it.
2. Inspect with `ffprobe`. Keep fps, size, and audio.
3. Run `scripts/apply_look.py`. Pass `--compare` when the user wants 处理前 / 处理后 side-by-side.
4. Spot-check stills at start, a turned-head frame, a hand-on-face frame if present, and end. Confirm blush sits on skin, not hair or clothes.
5. Report look display name, id, strength, layers, output path, and compare path if any.

## Command

```bash
python3 scripts/apply_look.py \
  --input /path/to/source.mp4 \
  --output /path/to/source_warm-peach.mp4 \
  --look warm-peach \
  --strength 1.0
```

Resolve `scripts/apply_look.py` from this skill folder.

Optional:

```bash
  --compare /path/to/source_warm-peach_compare.mp4 \
  --layers blush,lips,lids,warmth,smooth \
  --ffmpeg /opt/homebrew/bin/ffmpeg \
  --ffprobe /opt/homebrew/bin/ffprobe
```

`--layers blush` is blush-only. Default layers are the full 轻薄暖桃妆 set.

## Strength

`1.0` is the calibrated thin look. `0.7` is sheerer; `1.2` is more visible. Preview stills before going above `1.3`.

## Constraints

- Face tracking overlay only. Do not restyle hair, cat ears, jewelry, or wardrobe here.
- Keep the original audio. If stream copy fails, encode AAC.
- Locate `ffmpeg` / `ffprobe`; do not assume they are on `PATH`.
- The YuNet model is at `assets/face_detection_yunet_2023mar.onnx`.
