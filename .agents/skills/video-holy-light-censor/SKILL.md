---
name: video-holy-light-censor
description: Obscure a sensitive body region in a video with a tracked, feathered, pixel-level Gaussian blur, optionally adding a small white core, a sticker-style white glow with hand-drawn lettering and emoji-like decorations, or a pink hand-lettered Korean holy-light sticker (白色圣光 + 粉色文字). Supports several separate time intervals in one render, for example two different costumes in a change-outfit video. Use this skill when the user asks to 遮挡 / 打码 / 模糊 / 圣光遮挡 / 白光遮挡 / 闪光遮挡 / 表情包样式遮挡 / 粉色韩文圣光 / 韩国综艺圣光贴纸 a body area such as 大腿, 胯部, 胸部, 臀部, 大腿根部, 露出部位, or asks to 也遮挡 / 再加一段 for another costume or scene, or asks to apply a "圣光" censoring effect to a video. Do not use it for user-supplied GIF/PNG sticker overlays (use video-overlay-censor), fixed rectangular sticker or watermark covers (use video-exact-sticker-cover), or makeup and beauty overlays (use video-face-makeup).
---

# Video Holy-Light Censor

Blur a moving body region out of a video by tracking the region frame by frame and compositing a feathered Gaussian blur over it. The result reads as a soft frosted patch, not a sticker, so it survives camera motion without looking pasted on.

This skill owns the *decisions*: which interval needs work, where the region is, how strong the blur should be, and whether the output is acceptable. The script owns the *mechanics*: segmentation, tracking, compositing, and encoding.

## Inputs to collect

- The source video path. If the user sent a screenshot with a red box instead of a video, ask for the video.
- Which region to obscure, in the user's words (大腿 / 胯部 / 胸部 / 臀部 / 露出部位). Map it to one or two seed points in source pixels.
- The time range that needs covering. Inspect the whole clip first: a costume change or a cut usually means only part of the video needs the effect.
- Which look: pure blur (default), emoji-style white glow, or the pink Korean holy-light sticker (白色圣光 + 粉色文字).

If the user supplied a red-box screenshot, treat it as guidance, not as coordinates: map it to source pixels before use. Screenshots carry player chrome, padding, and scaling, so their pixel coordinates are not source-video coordinates.

## Procedure

1. Inspect the source with `ffprobe` before touching anything. Record width, height, frame rate, duration, frame count, and whether an audio stream exists. Do not assume 30 fps, 1080p, or a fixed duration.
   Reason: every downstream number (frame indices, zone radius, blur sigma) is derived from these, and a wrong frame rate silently desynchronises the effect from the motion.

2. Locate the region of interest. Extract candidate frames as PNG and view them; then pick seed points inside the target area in **source-video pixels**. Use skin segmentation in HSV to find the region, then track it — see [references/region-detection.md](references/region-detection.md) for thresholds, seed placement, and how to cut a region free from a neighbouring body part.
   Reason: the target moves. A static rectangle drifts off the subject within a second or two of camera motion.

3. Choose the interval that actually needs the effect. Find the costume change or cut by sampling frames across the clip, and set `--start` / `--end` to the affected range only.
   Reason: blurring the whole clip wastes time and risks degrading parts the user never complained about. It also burns encode quality on frames that never change.

4. Run the script:

   ```bash
   python3 /path/to/skills/video-holy-light-censor/scripts/blur_censor.py \
     --input /path/to/input.mp4 \
     --output /path/to/output.mp4 \
     --start 8.333333 --end 12.166667 \
     --seed 420,1570 --seed 770,1560 \
     --band 500,700 \
     --ffmpeg /opt/homebrew/bin/ffmpeg \
     --ffprobe /opt/homebrew/bin/ffprobe
   ```

   The seeds and the band in this example come from one specific clip; recompute all three for the video in front of you. `--seed X,Y` is a point inside the region to obscure; repeat it for a second region. `--region X,Y,W,H` tracks a fixed-size rectangle instead, for targets that are not skin or that sit in shadow. `--band X1,X2` drops a column range from the skin mask entirely, which both separates two nearby regions that would otherwise merge into one blob and removes a hand that is resting on the target. Without it, a thigh and the torso or a hand are detected as a single component and the blur lands in the wrong place.

   When the region is smooth skin or a shadow, template matching has no texture to latch onto. Give it context with `--track-pad N` (matching only — the blur still covers the region alone), keep the per-frame jump bounded with `--search-radius R`, and reject implausible matches with `--min-score S`.

   When the subject is redrawn between frames — generative video, a heavy costume change, a cut between a wide shot and a close-up — no image matcher can hold a lock. Locate the region by a semantic edge instead (the line where exposed skin meets the garment) and feed the per-frame boxes in with `--track-file`, a JSON array of `[frame, x, y, w, h]` rows whose frame index counts from the start of the interval. The recipe is in [references/region-detection.md](references/region-detection.md).

   The output must be a new `.mp4`; the script refuses to overwrite an existing path and refuses any output whose extension is not `.mp4`.

5. Verify before showing the result. Do not trust a zero exit code.

   - Re-probe the output: same dimensions, same frame rate, same duration, audio still present.
   - Extract frames from the middle and both ends of the covered range and look at them.
   - Measure the covered region numerically: within the target ROI, compare the source and output for mean brightness, `p99`, and standard deviation. The blur must reduce local contrast (std drops) without creating a bright spot (`p99` should fall, not rise).
   - Confirm the shape is gone, not just flattened. Look at the target: the leg or body outline must no longer be readable. A translucent veil that lifts the blacks can drop the std while leaving the silhouette perfectly legible, and that is not a successful censor.
   - Confirm no spill: the neighbouring garment or background must stay clean. A zone that is too wide leaves a grey smear across whatever is next to the target.

   Reason: a blur that is too weak leaves the detail legible; a white core that is too strong leaves a conspicuous hotspot that defeats the purpose of the effect; a veil that flattens the contrast without destroying the shape looks like a filter rather than a cover.

6. Iterate on the knobs rather than rewriting the pipeline. The defaults (`--blur 0.30 --zone-width 0.95 --zone-height 0.85 --plateau 0.78 --milk 2.0 --core 0.0 --sigma-max 26`) are the values that satisfied a real request; they are a starting point, not a law. The full knob ladder, the zone-size arithmetic, and the user-feedback-to-knob mapping are in [references/tuning.md](references/tuning.md).

   Sigma scales with the zone radius, which scales with the tracked box. A box much larger than the ~90 px the defaults were tuned on needs a larger `--sigma-max` to destroy the detail inside it, and a slightly tighter zone to stop the neighbours bleeding into the blur. Measure the ROI before and after instead of assuming the defaults transfer.

7. Deliver the output as a new file with an absolute path, and state which interval was covered and which parameters were used. Keep every earlier version; do not overwrite a previous delivery.

## Sticker-style white glow

Opt-in look for requests like 白光遮挡 / 闪光遮挡 / 表情包样式遮挡. The default pipeline stays a pure blur; `--sticker-style` adds an opaque feathered white light patch over the tracked region with hand-drawn lettering, hearts, exclamation marks and sparkles on top. The decal follows the tracked centre and breathes slightly, so it reads as a sticker reacting to the shot instead of a pasted rectangle.

```bash
python3 scripts/blur_censor.py \
  --input /path/to/input.mp4 --output /path/to/output_表情包白光.mp4 \
  --start 3.2 --end 6.466667 --region 270,500,160,130 --offset 20,10 \
  --zone-width 0.50 --zone-height 0.60 --plateau 0.70 --milk 5 --core 0.18 \
  --sticker-style --sticker-text "喵~" --glow 0.90 --glow-scale 1.00
```

| Flag | Default | What it controls |
|---|---|---|
| `--sticker-style` | off | enables the white light and decal layer |
| `--sticker-text` | `喵~` | hand-drawn lettering; pass `""` for symbols only |
| `--glow` | 0.90 | white opacity at the centre; lower it if the patch reads as a hotspot |
| `--glow-scale` | 1.30 | light radius relative to the blur zone radius |
| `--offset` | `0,0` | shifts the zone centre in pixels without changing the tracked template |

For a small patch — requests like 范围太大 / 小一半 / 只挡核心 — lower `--zone-width`, `--zone-height` **and** `--glow-scale` together. The visible white disc has radius `zone radius × glow-scale`, so shrinking only the blur leaves an oversized light. Halving both roughly halves the patch. Use `--offset DX,DY` to put the light on the exact target: measure the rendered patch centroid from a frame rather than assuming it equals the `--region` centre, because template tracking follows the subject and can land 20 px away.

Keep `--core` and `--milk` modest: the sticker layer already supplies the white, and a strong core underneath creates a hard bright rectangle. With the glow on, verification uses a different rule than pure blur — the ROI is meant to become bright and structureless, so check that no body outline survives and that the feathered rim stays off the neighbouring garment, rather than requiring `p99` to fall. The Chinese lettering needs a CJK font; without one the decals still render but the text is skipped.

## Pink Korean holy-light (白色圣光 + 粉色文字)

Use `--sticker-look korean` for requests like 粉色韩文圣光 / 韩国综艺圣光贴纸 / 白色圣光加粉色文字 / 只遮大腿根部及两侧. It replaces the emoji look with a soft white glow made of overlapping lobes and pink hand-lettered Hangul (`너무 귀여워` by default), rotated 17°, with quotation marks, exclamation marks, a dotted flourish, hearts, sparkles and pink dots. The look lives in `scripts/korean_holy_light.py`; tracking, interval selection, encoding and audio still come from `blur_censor.py`.

```bash
python3 scripts/blur_censor.py \
  --input /path/to/input.mp4 --output /path/to/output_粉色韩文圣光.mp4 \
  --start 3.4 --end 11.57 --region 0,0,720,1280 --offset 0,355 \
  --sticker-look korean --sticker-compact \
  --ffmpeg /path/to/ffmpeg --ffprobe /path/to/ffprobe
```

`--region 0,0,WIDTH,HEIGHT` locks the tracked centre at the frame centre; `--offset 0,355` then moves the light onto the hip band of a 720×1280 clip. For a moving subject, track a rectangle around the hip area instead and adjust `--offset` from a rendered frame. Use **one** region: the two lobes already cover both sides, and the script rejects a second one.

| Flag | Default | What it controls |
|---|---|---|
| `--sticker-look korean` | `emoji` | selects the pink Hangul look; also enables the sticker layer |
| `--sticker-compact` | off | two small hip lobes instead of the wide three-lobe glow; keeps the centre skirt and gold ornament visible |
| `--holy-size` | `auto` | light half-width,half-height in source pixels; `auto` uses `0.60 × width, 0.185 × height` |
| `--holy-lobes` | off | custom lobes `dx,dy,rx,ry;...` in source pixels relative to the light centre; overrides the preset wide/compact layout. Use `--holy-lobes=...` when the first value is negative |
| `--glow-scale` | 1.00 | multiplier on `--holy-size` |
| `--glow` | 0.90 / 0.87 | white opacity at the centre (wide / compact) |
| `--sticker-text` | `너무 귀여워` | Hangul lettering; pass `""` for symbols only |
| `--offset` | `0,0` | moves the light centre without changing the tracked template |

The korean look owns its own light-shaped Gaussian blur and whitening. It therefore skips the elliptical zone blur, `--core` and `--milk`; `--blur`, `--zone-width`, `--zone-height`, `--plateau` and `--sigma-*` have no effect with this look. Do not stack both looks.

**Wide vs compact.** Without `--sticker-compact`, three lobes cover the whole hip band and wash the centre garment white; that was rejected as 范围太大 on the reference clip. `--sticker-compact` is the approved setting for 只遮大腿根部及两侧: left/right lobe opacity ≈ 0.87, centre ≈ 0.35, top ≈ 0, so the black skirt and gold waist ornament stay readable. Shrink further with `--glow-scale` or `--holy-size`, not by re-enabling the zone blur.

**Font.** Lettering needs a Korean handwriting face, resolved from `NanumScript.ttc` (macOS asset font, face index 1) with `AppleSDGothicNeo.ttc` as the last candidate. If no candidate exists and text is non-empty, the script fails with an explicit error instead of silently dropping the lettering. Pass `--sticker-text ""` for symbols only when no Korean font is available.

**Verification.** Same frame count, fps, dimensions and audio as the source. On the reference 720×1280 / 30 fps clip, the two marked hip ROIs dropped from std 60.7 to 24.7, while the upper body (y < 700) stayed at 0.88 mean absolute difference and frames outside the interval at 0.77. Check that the black skirt between the lobes is still visible — that is the point of the compact look — and that no skin triangle survives at the lobe rims.

**Misaligned target boxes.** The compact preset assumes two lobes at roughly the same height. When the user's two red boxes differ in height or size, map them to source pixels with a homography and pass their centres and radii through `--holy-lobes` instead. Each `dx,dy,rx,ry` is relative to the light centre: `dx,dy` is the lobe centre offset in source pixels, `rx,ry` its half-axes. The canvas grows to fit the lobes, and the look adds an elliptical falloff, a 15 px feather and a light-shaped blur, so the two patches read as soft glow rather than white cards.

If the subject moves sideways across the shot, a fixed `--region 0,0,W,H` will leave one side exposed. Locate a rigid costume detail (a belt ornament, a buckle) frame by frame, interpolate the low-confidence frames, and feed one box per frame through `--track-file`. Keep the centre of that box at the light centre. For a close-up or transition where the target is not in frame, put the box centre far outside the frame so the compositor clips the light away entirely. See [references/tuning.md](references/tuning.md) for a worked example and measured values.

## Several intervals in one render

Use `--segment` when one clip needs the same treatment in more than one time range — for example a change-outfit video where two costumes must be covered. Each segment has its own interval, tracked rectangle, offset and temporal smoothing; blur, white glow, lettering and every other look parameter stay shared, so both patches read as the same effect. The video is still encoded once from the original frames, so an already-approved segment is not re-encoded.

```bash
python3 scripts/blur_censor.py \
  --input /path/to/input.mp4 --output /path/to/output_two_costumes.mp4 \
  --segment "start=3.2;end=6.466667;region=270,500,160,130;offset=20,40;smooth=2" \
  --segment "start=9.933333;end=13.033333;region=270,500,160,130;offset=1,76;smooth=12" \
  --zone-width 0.40 --zone-height 0.48 --blur 0.41 --plateau 0.70 --milk 5 --core 0.18 \
  --sticker-style --sticker-text "喵~" --glow 0.90 --glow-scale 1.00
```

| Key | Required | What it controls |
|---|---|---|
| `start` / `end` | yes | interval in seconds, inside the video duration |
| `region` | yes | `X,Y,W,H` template to track in that interval |
| `offset` | no | `DX,DY` pixel shift for that segment's patch |
| `smooth` | no | temporal smoothing of that segment's track; defaults to `--smooth` |

Segments may be given in any order; they are sorted and must not overlap. Do not mix `--segment` with `--start` / `--end` / `--region` / `--seed`. The JSON summary lists each one under `segments`. Frames outside every segment come straight from the source, so adding a second segment leaves an existing one bit-identical.

Treat each costume as a separate tracking problem even when the actor stands in the same place. Measure the per-segment centre spread first; a new costume can make the light wander out of the marked box. Raise that segment's `smooth` rather than enlarging its zone, which would undo a size the user already approved. Find interval boundaries from exact frame differences rather than `-ss` thumbnails, and map screenshot annotation boxes with a homography before choosing the second `offset`.

## Output contract

- A new `.mp4` file with the original dimensions, frame rate, and duration, with the source audio preserved (`--audio copy` by default; use `--audio aac` when the source audio cannot be stream-copied).
- Frames outside the processed interval are re-encoded from the original and are visually unchanged.
- The script prints a JSON summary with the interval, frame range, reference frame, region count, tracking mode, and blur fraction. Report the relevant fields when handing the result over.

## Failure handling

- **No skin region found at the seed.** The seed is off the target or the HSV thresholds do not match this footage. Re-extract the frame, view it, and pick the seed again. Adjust `--hue/--sat/--val` only after confirming the seed lands inside the target.
- **The blur lands on the wrong body part.** Two regions merged into one component. Add `--band` to cut them apart, or use `--region` to track a rectangle directly.
- **The mask jitters or slides.** Raise `--smooth` to smooth the track over time, or move `--reference-frame` to a frame where the target is clearly visible.
- **The tracked box drifts off the target (`--region` mode).** The template had no texture to match on and the search window let it wander. Add `--track-pad 60–100` to give the match surrounding context, tighten `--search-radius` to 15–25, and set `--min-score` around 0.6 so an implausible frame holds position instead of jumping.
- **The tracked box slides sideways although the target is still.** The subject's own outline changed — a hand swept in front of the target — so the reference template no longer matches. Check by matching each frame against the previous one: if the frame-to-frame centre never moves, the target is stationary and the template is the problem. Lock the box with `--search-radius 3` and `--min-score 0.95`, or split the interval. See [references/region-detection.md](references/region-detection.md).
- **The blur sits on the costume instead of the skin.** The framing changed between shots, so the body moved and rescaled inside the frame. Locate the region by a semantic edge per frame and pass the boxes in with `--track-file` instead of relying on the matcher.
- **The tracked box lags behind the target.** `--search-radius` is smaller than the real per-frame displacement. Raise it.
- **The box is correct at the start but wrong later.** `--reference-frame` points at a frame the target had already moved away from. Set it to the frame the user's box was drawn on — see the screenshot-mapping procedure in [references/region-detection.md](references/region-detection.md). Remember that the value counts from the start of the interval, not from the start of the video; it is clamped rather than rejected, so a wrong number produces a wrong track instead of an error.
- **The output looks like a white glow instead of a blur.** `--core` is non-zero or `--milk` is too high. Set `--core 0` and lower `--milk`.
- **The detail is still legible.** Raise `--blur` (stronger sigma) and/or `--zone-width` / `--zone-height` (larger footprint). Raising `--blur` too far dissolves the body shape; the region stops reading as a leg.
- **The script exits non-zero.** Read stderr. A `CalledProcessError` carries the FFmpeg message. The temporary work directory is created next to the output and is removed on exit, including on failure.
- **Korean lettering fails with a font error.** Install Nanum Pen Script (`NanumScript.ttc`) or pass `--sticker-text ""` to keep the pink symbols only. The script never silently drops the lettering.
- **The pink light washes the whole skirt.** `--sticker-compact` is missing, or `--glow-scale` / `--holy-size` is too large. Start with `--sticker-compact --glow-scale 1.0`.
- **Encoding fails on the final mux.** Check disk space for the PNG frame cache; rendering holds full-canvas frames on the output volume.

## Boundaries

- This is pixel-level blur compositing over a tracked region, not semantic detection and not an opaque cover. A strong blur reduces legibility; it is not a guarantee of concealment, and it does not survive a re-encode that sharpens the image.
- Do not use it to cover a watermark, logo, or fixed sticker — those have stable bounds and belong to `video-exact-sticker-cover`. Do not use it to paste a GIF or PNG over the subject — that is `video-overlay-censor`.
- Never crop, retarget, resize, replace, or overwrite the user's source media, and never write into a live `.palmier` package.
- Only CFR, unrotated SDR video is validated here. VFR timing, rotation, HDR metadata, and subtitle or data tracks are not preserved by design; inspect these before use and report unsupported inputs rather than promising lossless preservation.
- Rendering is not a streaming renderer. It materialises one PNG per frame for the covered interval; check disk capacity on long clips.

## Examples

Input: `用 video-holy-light-censor 把这个视频大腿露出来的部分挡一下：/path/to/source.mp4`

Output: a new `source_圣光遮挡.mp4` where the exposed thigh region in the affected interval is covered by a soft feathered blur, with the rest of the clip and the audio untouched.

Input: `用 video-holy-light-censor 给变装后的片段加粉色韩文圣光，只遮大腿根部及两侧：/path/to/source.mp4`

Output: a new `source_粉色韩文圣光.mp4` with `--sticker-look korean --sticker-compact`: two soft white lobes on the hip sides, pink hand-lettered Hangul over them, and the centre costume still visible.

## Windows (win32) platform notes

The script is cross-platform Python, but FFmpeg and ffprobe are external executables. On Windows, install them and pass the real paths instead of the Homebrew ones, for example `--ffmpeg "C:/ffmpeg/bin/ffmpeg.exe" --ffprobe "C:/ffmpeg/bin/ffprobe.exe"`. Run it as `python scripts/blur_censor.py ...` — the Windows launcher is usually `python`, not `python3`. There are no bash-only constructs inside the script itself.
