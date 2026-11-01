---
name: video-holy-light-censor
description: Obscure a sensitive body region in a video with a tracked, feathered, pixel-level Gaussian blur, optionally adding a small white core. Use this skill when the user asks to 遮挡 / 打码 / 模糊 / 圣光遮挡 a body area such as 大腿, 胯部, 胸部, 臀部, or 露出部位, or asks to apply a "圣光" censoring effect to a video. Do not use it for GIF/PNG sticker overlays (use video-overlay-censor), fixed rectangular sticker or watermark covers (use video-exact-sticker-cover), or makeup and beauty overlays (use video-face-makeup).
---

# Video Holy-Light Censor

Blur a moving body region out of a video by tracking the region frame by frame and compositing a feathered Gaussian blur over it. The result reads as a soft frosted patch, not a sticker, so it survives camera motion without looking pasted on.

This skill owns the *decisions*: which interval needs work, where the region is, how strong the blur should be, and whether the output is acceptable. The script owns the *mechanics*: segmentation, tracking, compositing, and encoding.

## Inputs to collect

- The source video path. If the user sent a screenshot with a red box instead of a video, ask for the video.
- Which region to obscure, in the user's words (大腿 / 胯部 / 胸部 / 臀部 / 露出部位). Map it to one or two seed points in source pixels.
- The time range that needs covering. Inspect the whole clip first: a costume change or a cut usually means only part of the video needs the effect.
- Whether the user wants pure blur or blur plus a visible white glow. Default to pure blur.

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

## Output contract

- A new `.mp4` file with the original dimensions, frame rate, and duration, with the source audio preserved (`--audio copy` by default; use `--audio aac` when the source audio cannot be stream-copied).
- Frames outside the processed interval are re-encoded from the original and are visually unchanged.
- The script prints a JSON summary with the interval, frame range, reference frame, region count, tracking mode, and blur fraction. Report the relevant fields when handing the result over.

## Failure handling

- **No skin region found at the seed.** The seed is off the target or the HSV thresholds do not match this footage. Re-extract the frame, view it, and pick the seed again. Adjust `--hue/--sat/--val` only after confirming the seed lands inside the target.
- **The blur lands on the wrong body part.** Two regions merged into one component. Add `--band` to cut them apart, or use `--region` to track a rectangle directly.
- **The mask jitters or slides.** Raise `--smooth` to smooth the track over time, or move `--reference-frame` to a frame where the target is clearly visible.
- **The tracked box drifts off the target (`--region` mode).** The template had no texture to match on and the search window let it wander. Add `--track-pad 60–100` to give the match surrounding context, tighten `--search-radius` to 15–25, and set `--min-score` around 0.6 so an implausible frame holds position instead of jumping.
- **The tracked box lags behind the target.** `--search-radius` is smaller than the real per-frame displacement. Raise it.
- **The box is correct at the start but wrong later.** `--reference-frame` points at a frame the target had already moved away from. Set it to the frame the user's box was drawn on — see the screenshot-mapping procedure in [references/region-detection.md](references/region-detection.md).
- **The output looks like a white glow instead of a blur.** `--core` is non-zero or `--milk` is too high. Set `--core 0` and lower `--milk`.
- **The detail is still legible.** Raise `--blur` (stronger sigma) and/or `--zone-width` / `--zone-height` (larger footprint). Raising `--blur` too far dissolves the body shape; the region stops reading as a leg.
- **The script exits non-zero.** Read stderr. A `CalledProcessError` carries the FFmpeg message. The temporary work directory is created next to the output and is removed on exit, including on failure.
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

## Windows (win32) platform notes

The script is cross-platform Python, but FFmpeg and ffprobe are external executables. On Windows, install them and pass the real paths instead of the Homebrew ones, for example `--ffmpeg "C:/ffmpeg/bin/ffmpeg.exe" --ffprobe "C:/ffmpeg/bin/ffprobe.exe"`. Run it as `python scripts/blur_censor.py ...` — the Windows launcher is usually `python`, not `python3`. There are no bash-only constructs inside the script itself.
