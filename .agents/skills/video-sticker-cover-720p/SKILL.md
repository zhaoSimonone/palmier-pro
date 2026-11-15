---
name: video-sticker-cover-720p
description: |
  Hide a fixed anime/photo sticker burned into a portrait video and export a 720p MP4 in one encode.
  Load this skill when the user says 遮挡贴图 / 动漫贴图遮挡 / 贴图版变装前 / 生成720p / 视频被IP拦截,
  or when a video rejected by a generation platform (Seedance, CapCut) must be cleaned and re-exported at 720x1280.
  Do NOT use for moving or keyframed overlays, faces, inpainting, subtitle transcription, or plain re-encoding
  with nothing to hide; use video-exact-sticker-cover when only a rectangle cover is needed and no 720p export.
---

# Sticker Cover + 720p Export

## Inputs to collect

- Source video path. Never reuse an earlier rendered output as the source.
- Target size. Default `720x1280` for portrait clips; the platform floor is 409,600 px, so 720x1280 (921,600) clears it.
- Whether burned-in character-name text must also be hidden. Default: leave text alone unless the user asks.

## Procedure

1. Probe with `ffprobe`: require constant frame rate, progressive, no rotation, SDR, and note frames/duration/audio.
   Frame-exact windows and the single-pass scale both assume CFR; a VFR or rotated source invalidates the timing.

2. Locate the sticker with `scripts/measure_region.py`. Pick `--region X,Y,W,H` that frames the sticker **plus working background margin** (roughly 10–20% each side).
   The script decodes frames, accumulates temporal variance, and reports sticker/background levels, per-edge crossings, two candidate rects, presence spans, and gradient peaks. Presence is judged on a ring just inside the chosen rect, so keep the sticker centred in the window.
   Pass `--work-dir DIR` when the frames must stay inside a specific scratch directory; otherwise it uses the system temp dir and cleans up after itself.

3. Treat `suggestedRect` as a starting point, not the answer. The script reports two independent rects:
   - `rects.gradient` — edges from the strongest luminance step in the outer band of each side. It wins whenever all four strengths clear `10`, because a card-style sticker whose artwork animates inside still has a hard border while its interior is *not* static.
   - `rects.variance` — edges from the temporal-variance 50% crossing. It is the fallback for stickers that blend into the scene, and it shrinks toward the stillest inner area when the artwork moves. A variance rect noticeably smaller than the gradient rect is a warning sign, not a tighter fit.
   - Hard edge vs soft edge: a single-pixel step (gradient 80–200, or 20–50 on muted stickers) needs no extra margin; a 2–10 px ramp means the clip was upscaled or blurred, the crossing sits inside the ramp, and each side must be extended until the fringe variance returns to background.
   Reason: a 1–2 px leftover of sticker ink survives as a visible halo and still carries the character silhouette. Worked edge numbers and the alpha table are in `references/measurement.md`.

4. Render with `scripts/cover_export.py`, one `--rect X,Y,W,H[@START,END]` per region (repeatable) and `--size 720x1280`.
   `START`/`END` are **seconds**, not frame numbers; the script converts them to inclusive frame indices. Omitting the suffix covers the whole clip.
   Drawing at source coordinates and scaling in the same filter chain means a single encode instead of render-then-downscale.

5. Verify with `scripts/verify_cover.py --output OUT.mp4 --source SRC.mp4 --rect ... --color ...`. It decodes both clips, reports per-rect block mean/std/max-brightness, a temporal-variance ring on all four sides, the outside-region difference, audio, and a pass/fail verdict with the reasons. Pass `--work-dir` when the frames must stay in a given scratch directory.
   What each number means:
   - Block: mean matches the requested color within 3 (ffmpeg maps `58,58,58` through the source matrix, so 56 is normal) and std < 2.5.
   - Ring: the adjacent band must not sit far *below* the band 4–8 px further out. A dip means a leftover fringe; extend that side 1–2 px and re-render. Judge this on the native-resolution render — after a non-integer downscale a dip can be the resampler.
   - Outside diff: compare against a *no-cover* re-encode of the same source with the same crf/scale. crf 18 plus lanczos already costs ~2/255; the cover itself should add ≈0 (under 0.05). An absolute "1.5/255" ceiling is unreachable and sends you chasing encoder noise.
   - Audio present, frame count and duration unchanged, source mtime untouched.

6. Check the entrance and exit frames for **transient sticker content outside the steady rect**. Sticker overlays often animate in: glitch strips, zoom-in card frames, or a title bar that lands before the artwork. Sample the first and last ~20 frames and look above/below/around the rect for the sticker's own colors (for example a saturated green or cyan band).
   This matters because a steady-state rect is measured on the settled frames and leaves the entrance artefact fully visible; on one 174-frame clip a green glitch band survived 12 frames that way. Cover it with a second rect carrying its own `@START,END` window rather than enlarging the main rect for the whole clip.

7. Read the first and last frames before trusting `presence`. `presence` lists the *stable* spans; a fade-in, a blurred entry animation, or a slow reveal still carries the sticker and must be covered. Cover from the first frame that shows any sticker content, and leave only fully black frames out — painting grey onto black is a visible change.

8. Deliver the MP4 path, the rects and frame windows, the verification numbers, and any residual judgement call (for example artifacts clipped by the cover).

## Output contract

- A new `.mp4` at the requested size; never overwrite the source or an existing output.
- Cover colour is opaque neutral grey by default; no outline, padding, feather or safety margin beyond the measured edge.
- Report: output path and size, rect(s) with frame ranges (state seconds for windows), per-frame verdicts, audio handling, source untouched.

## Failure handling

- `no static rectangle found` → the overlay is animated or the region lacks contrast. Do not force a rectangle; tell the user the fixed-rect workflow does not apply.
- Sticker moves, rotates or scales over time → this workflow is invalid; say so instead of covering a moving target with one box.
- Odd target dimensions → `yuv420p` needs even numbers; the script rejects them, pick 720x1280 or another even size.
- Output already exists → the script refuses. Choose a new filename rather than overwriting.

## Examples

Input: `遮挡这个视频的动漫贴图并生成720p：/path/v.mp4` (1080x1920, 174 frames, card-style sticker)
Output: `measure_region.py --region 210,1030,670,700` → gradient rect `276,1084,528,570`, strength 132/20/98/74 (the variance rect came back as `341,1123,463,607`, i.e. too small because the artwork inside the card animates), then `cover_export.py --rect 276,1084,528,570 --size 720x1280` → 720x1280, 174 frames, block 58.0 with std 0.11, covered-area max brightness 255→61, outside diff 2.088/255 against a no-cover baseline of 2.083.

Input: same clip, but the burned-in caption must go too
Output: add a second rect with its own window, e.g. `--rect 200,1020,520,44@0.53,4.9`, so the text is covered only while it is on screen.

## Windows (win32) platform notes

- Replace `python3` with `python`, and pass `--ffmpeg`/`--ffprobe` only when `ffmpeg` is not on `PATH`.
- Use PowerShell quoting (`--rect "276,1084,528,570"`); the `@START,END` window is in seconds and contains a comma, so keep the whole value inside one quoted argument.
- Do not rely on the system temp dir or `/tmp`; pass `--work-dir` to `measure_region.py` and explicit output paths to `cover_export.py`.
