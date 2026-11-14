# Tuning and verification

The knob ladder, the feedback-to-knob mapping, and the numeric checks that decide whether an iteration is an improvement.

## The knobs

| Flag | Default | What it controls |
| --- | --- | --- |
| `--blur` | 0.30 | blur sigma as a fraction of the zone half-width. Higher = more detail destroyed. |
| `--sigma-min` / `--sigma-max` | 16 / 26 | clamps on the computed sigma in pixels. |
| `--zone-width` | 0.95 | zone radius as a multiple of the tracked box width. |
| `--zone-height` | 0.85 | zone radius as a multiple of the tracked box height. |
| `--plateau` | 0.78 | inner fraction of the zone that gets the full blur; the rest feathers out. |
| `--milk` | 2.0 | brightness lift inside the blur (frosted look). |
| `--core` | 0.0 | white core opacity at the centre. 0 disables it. |
| `--smooth` | 2.0 | temporal smoothing of the tracked centre, in frames. |
| `--offset` | `0,0` | pixel shift applied to the tracked centre before blur, white core and glow compositing. | See "Moving a small patch onto the lower part of the target" below. |
| `--reference-frame` | middle | frame used to seed the tracking. Set it to the frame the user's box was drawn on, not the interval midpoint — the tracker pins the box there. It counts from the start of the interval, not from the start of the video. |
| `--min-area` | auto | smallest skin blob in pixels that may be tracked. Auto derives it from the frame size (about 0.06% of the frame area, floored at 400 px). Raise it when a small skin-coloured accessory is being picked up as the target. |
| `--hue` / `--sat` / `--val` | `5,34` / `85,180` / `120,250` | the HSV window used for skin detection. |
| `--track-pad` | 0 | extra pixels of context added around a `--region` box **for matching only**. The blur still covers the region alone. Raise it when the target is smooth skin or shadow with no texture of its own. |
| `--search-radius` | 60 | how far a `--region` template's centre may move per frame, in pixels. |
| `--min-score` | 0.0 | hold the previous position when the best template match scores below this (0–1). 0 accepts every match. |
| `--track-file` | none | per-frame boxes from an external tracker, as a JSON array of `[frame, x, y, w, h]` with interval-relative frame indices. Overrides the built-in tracking and is used as-is, unsmoothed. |

## Zone size arithmetic — get this right first

The zone radius is `rx = --zone-width × (tracked box width)`, and the ellipse is centred on the box centre. So the ellipse spans `zone-width × box_width` in total. A multiplier of 1.5 therefore produces an ellipse **three times** the width of the skin region, and a multiplier of 0.95 produces one that is just under twice as wide.

The feathered rim lands at the ellipse boundary, so a multiplier that is too high pushes the rim onto the neighbouring garment and leaves a wide grey smear across it. Too low and the corners of a triangular limb fall outside the fully blurred core, leaving the tips exposed.

Start at the default 0.95 / 0.85 and move in one direction at a time. Raise it if the corners of the limb are still readable; lower it if the neighbouring garment is smudged.

## Template tracking (`--region`) — the three knobs that decide whether it holds

`--region` mode matches a patch of the reference frame with normalised cross-correlation. Three knobs control how well it stays locked, and they only apply to `--region`, not to `--seed`:

- `--track-pad N` grows the **matched** template by N pixels of context on every side while the **reported** box stays the size you asked for. This is the fix for a target with no texture of its own — bare skin, a shadowed cleavage, a smooth gradient. Without context, the normalised correlation has nothing to anchor on and drifts. The blur footprint is unaffected: the zone is still computed from the region box.
- `--search-radius R` bounds how far the centre may move per frame. The search window is `centre ± (template_half + R)`, so R is literally the per-frame displacement limit. A large radius lets the tracker jump across the body onto a similar-looking patch.
- `--min-score S` holds the previous position when the best match scores below S. A low score means the match is not trustworthy, and following it is worse than standing still.

Measured on a real clip where the target was a 91×90 region over a moving chest: with `pad=0` the track covered the region on average 85% of the frames and failed outright on 10 of 120 frames, with single-frame jumps of 80–102 px. With `pad=90`, `search-radius=20`, `min-score=0.65` the coverage rose to 95% with **zero** failed frames.

Watch out for the trap in the middle: if `--search-radius` is smaller than the target's real per-frame displacement, the tracker lags behind the subject — it stays locked on the *pattern* it was matching, which is correct behaviour, not a bug. Raise the radius rather than blaming the matcher.

**Padding is not always the answer.** It helps a small, textureless target. It hurts a large one: on a 217×184 region the template already carries plenty of structure, so `pad=0` scored best (91% mean coverage, 0 failed frames) while `pad=120` dropped to 86%. Extra padding on a big box pulls moving hands and swinging hair into the template, and those are exactly the parts that change. Measure coverage before reaching for `--track-pad`.

## Sigma reaches beyond the zone

Sigma is the standard deviation of the Gaussian, so the blur kernel spreads roughly `3 × sigma` in each direction. A sigma of 48 reaches about 144 px — far enough to pull the black thigh-high band and the dark background into the thigh's blur and turn it into a dark smear. `--sigma-max 26` keeps the kernel inside the zone.

When the covered region comes out **darker** than the source, that is the signature of sigma reaching into a dark neighbour. Lower `--sigma-max` before touching anything else.

## A big box needs a bigger sigma

`sigma = --blur × rx`, and `rx` scales with the tracked box. A 91×90 box gives `rx ≈ 86` and a sigma of 26; a 217×184 box gives `rx ≈ 191`, where the same `--blur 0.30` asks for a sigma of 57. The default `--sigma-max 26` clamps that hard, and the result is a 217 px patch with a 26 px blur — the detail inside is only lightly softened and stays readable.

So the clamp has to move with the target: for a 217×184 region, `--sigma-max 52–60` restores the intended detail destruction. The cost is real — a large sigma drags the neighbouring colours into the blur, so the ROI mean drops further and the patch picks up their tint. Counter it by shrinking the zone rather than by weakening the blur:

| Box | Zone | Sigma max | Measured spatial high-frequency | ROI mean |
| --- | --- | --- | --- | --- |
| 217×184 | 0.95 / 0.85 | 60 | −75.6% | −6.1% |
| 217×184 | 0.88 / 0.78 | 52 | −68.7% | −5.2% |

Both hide the target completely. The tighter zone keeps the garment's edge clean and the tint bleed smaller, at the cost of a slightly softer blur. When the covered region is large, start tighter than the default.

## Mapping user feedback to a change

This ladder came out of a real six-round iteration. Read the complaint, change one knob, re-render, re-measure.

| The user says | Change | Why |
| --- | --- | --- |
| "太亮了" / "有个亮点" | `--core 0` | The white core is a separate feature from the blur. Turning it off is the fix; raising `--milk` makes it worse. |
| "还是太亮，像蒙了一层白" | `--milk` down to 1–2 | A large lift turns the blur into a bright veil. |
| "范围不够大" / "没挡住" | `--zone-width` / `--zone-height` up | The footprint grows. The blur radius (`--blur`) does not change, so the texture inside stays equally destroyed. |
| "看不清了" / "还是能看出来" | `--blur` up | More sigma = less detail. Watch for the leg losing its shape. |
| "看起来像贴上去的" | `--plateau` up | A larger plateau makes the fully-blurred core bigger relative to the feathered rim. |
| "边在抖" / "糊块在飘" | `--smooth` up | Temporal jitter in the tracked centre. |
| "旁边白衣服脏了" / "糊到裙子上" | `--zone-width` / `--zone-height` down | The rim has spilled onto the neighbouring garment. |
| "范围太大" / "小一半，只挡核心" | `--zone-width`, `--zone-height` **and** `--glow-scale` down together | With the sticker layer on, the visible disc radius is `zone radius × --glow-scale`. Halving both roughly halves the white patch; shrinking only the blur leaves an oversized disc. |
| "光斑偏了" / "没对准" | `--offset DX,DY` | Nudges the cover without reseeding the tracker. Measure the rendered patch centroid first — template tracking follows the subject and can land 20 px away from the `--region` centre. |
| "腿变黑了" | `--sigma-max` down | The blur is reaching into a dark neighbour. |
| "糊块飘了 / 跟不上" (region mode) | `--track-pad` up, `--search-radius` up | The template had no context to match on and the window was too tight to follow the motion. |
| "糊块位置不对 / 自己乱跑" (region mode) | `--search-radius` down to 3–5, `--min-score` up to 0.9–0.95 | The subject deformed, so the reference template no longer matches and the match slides onto a neighbouring region. A tight window with a high confidence floor holds the box where it was verified. |
| "糊块卡住不动" (region mode) | `--min-score` up | The match was below the confidence floor and the position was being held. |

Push in this order: disable the core, enlarge the zone, then deepen the blur. Deepening the blur first dissolves the body shape and is hard to undo.

## Default recipe that worked

```
--blur 0.30 --zone-width 0.95 --zone-height 0.85 --plateau 0.78 --milk 2.0 --core 0.0
--sigma-min 16 --sigma-max 26 --smooth 2.0
```

With seeds and a band chosen for the clip, this produced a soft, evenly feathered patch with no hotspot, no legible detail, and no smear on the neighbouring garment. An earlier, wider recipe (`--zone-width 1.50 --zone-height 1.08 --blur 0.20 --sigma-max 48`) hid the target too, but left a broad grey veil across the white costume and pulled the dark background into the blur; the tighter recipe above is the better starting point.

## Small core patch with the sticker glow

Verified on a 720×1280 change-outfit clip, Kitty cat costume, interval 3.2–6.4667 s (frames 96–194). The first delivery used `--zone-width 0.78 --zone-height 0.78 --glow-scale 1.30`; its white disc spanned roughly (221,467)–(431,650) and washed over the neck and shoulders. The user asked for about half that footprint, covering only the cleavage.

```
--region 270,500,160,130 --offset 20,10
--zone-width 0.50 --zone-height 0.60 --plateau 0.70 --blur 0.34 --sigma-max 26
--milk 5 --core 0.18 --smooth 2.0
--sticker-style --sticker-text "喵~" --glow 0.90 --glow-scale 1.00
```

The disc shrank to roughly (275,497)–(380,609), about 29% of the original area; the neck and shoulder ROIs returned close to the source while the cleavage ROI stayed strongly changed. Frames outside the interval remained within about 1.2 mean absolute difference.

A further ~20% reduction uses `--zone-width 0.40 --zone-height 0.48 --blur 0.41` with `--glow-scale 1.00`. Raise `--blur` as the zone shrinks so `blur × rx` still reaches the `--sigma-max 26` ceiling; otherwise the smaller patch also blurs more weakly. Keep `--glow-scale` at 1.00 and let the zone carry the scaling — the white disc and its blur then shrink together.

Two rules from that round:

- The light radius is `zone radius × --glow-scale`, so both must shrink together. Lower `--plateau` slightly when the smaller ellipse would otherwise leave a hard rim.
- Apply a position offset once to the tracked centre, not separately in the blur, core and glow loops. Missing one layer leaves a bright disc that no longer sits over its own blur.

## Moving a small patch onto the lower part of the target

When the user marks a region in a screenshot (usually a red rectangle drawn on a player capture), do not eyeball the offset. The screenshot is cropped or displayed at a different aspect ratio than the source video, so its pixel coordinates are not source coordinates. Detect the rectangle by colour, then map its corners into source pixels with a SIFT homography against a rendered frame:

```python
sift = cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.02)
k1, d1 = sift.detectAndCompute(cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY), None)
k2, d2 = sift.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None)
good = [m for m, n in bf.knnMatch(d1, d2, k=2) if m.distance < 0.75 * n.distance]
H, inliers = cv2.findHomography(p1, p2, cv2.RANSAC, 4.0)
box_in_video = cv2.perspectiveTransform(box_in_screenshot, H)
```

On the Kitty cat clip a 460x610 screenshot mapped to x 279-417, y 577-693, while the rendered disc centroid was (346, 567) — the disc ended exactly at the top edge of the marked box, which is why the lower V-shaped shadow stayed visible. Raising only `--offset` Y from 10 to 40 (centre to (346, 597)) fixed it, with the disc still 88x94 px.

Measure the trade-off instead of pushing the offset until it looks right. In the lower-cleavage ROI (330,600)-(385,645), dark pixels (<160) went 6.4% -> 0.3% and std 28.5 -> 18.2; the upper-cleavage ROI stayed bright (mean about 241), and the neck/shoulder ROIs did not change. Pushing Y another 6 px began to expose the upper cleavage and wash out the bell on the bow. The useful window is narrow: pick the smallest Y that clears the dark pixels, and leave `--zone-width` / `--zone-height` untouched so an earlier "make it smaller" request is not silently undone.

## One clip, several costume changes

`--segment` repeats an independent interval with its own `region`, `offset` and `smooth` while sharing every look parameter. Render all segments in one pass: stacking a second render on an already-delivered file re-encodes the first segment and quietly degrades it. The multi-segment concat graph pulls uncovered frames from the source and covered frames from the rendered PNG sequence, so an unchanged segment stays bit-identical to its earlier render — mean absolute difference 0.000 on the Kitty cat segment after adding the Bunny segment.

Treat each costume as a separate tracking problem even when the actor stands in the same place. On that clip the same `--region` produced centre spreads of (12.9, 21.8) px and (11.1, 16.1) px with `--smooth 2`. With a small patch the second costume's light drifted below the marked box; `smooth=12` cut the spread to (5.3, 2.2) px and held the patch inside the box for the whole interval. Raising `smooth` beats enlarging `--zone-height` here, because it keeps the footprint the user already approved.

Find interval boundaries from exact frame differences, not `-ss` thumbnails: a hard cut can land between two seek samples. Map the screenshot's annotation box with a homography before choosing the second segment's `offset`; the two costumes' target centres were (346, 597) and (330, 620) — close, but not interchangeable.

## Numeric verification

Do not verify by eyeballing only. Pick a frame in the middle of the covered range, define the target ROI in source pixels, and measure:

```python
import cv2, numpy as np
box = (323, 1436, 516, 1673)          # x0, y0, x1, y1 in source pixels
for tag, path in (("source", "src.png"), ("output", "out.png")):
    roi = cv2.imread(path)[box[1]:box[3], box[0]:box[2]].max(axis=2)
    print(f"{tag:7s} mean={roi.mean():6.1f} max={roi.max():3d} "
          f"p99={np.percentile(roi, 99):.0f} std={roi.std():5.1f}")
```

How to read it:

- **std** is the local-contrast measure. A working blur drops it substantially — in the reference run, from 88.7 to about 55. If std barely moved, the blur is too weak or the ROI is off the target.
- **p99** guards against a hotspot. A bright core or an excessive `--milk` lifts p99 and max. In the reference run p99 fell from 252 to about 235 and max fell from 255 to about 240, which is what a non-hotspot blur looks like.
- **mean** should stay close to the source mean. A large drop means the region has turned into a dark smear; a large rise means it has turned into a white veil.

Use `max` over channels rather than a single channel: it is the strictest measure of "is anything still legible here". With `--sticker-style`, the ROI is meant to become bright and structureless, so check that no body outline survives instead of requiring p99 to fall.

## A veil is not a blur

A flat, semi-transparent overlay that lifts the blacks can drop the ROI standard deviation while leaving the target completely readable. The number looks good, the picture does not. This is the single most common way a censor fails while still passing a naive contrast check.

Two checks distinguish them:

1. **Look at the target.** The body outline must no longer be readable as a body part. If you can still tell it is a leg, the effect is a veil.
2. **Check the mean.** A veil that lifts the blacks raises the mean and flattens it. A real blur pulls surrounding pixels into the target and keeps the mean near the source value. A covered region whose mean has dropped by more than a few percent is absorbing dark surroundings — lower `--sigma-max` and shrink the zone.

## Checks beyond the ROI

- Compare the full frames of source and output side by side, not just the crop. A zone that is too large leaves a visible smudge on the neighbouring garment.
- Measure the rendered light patch centroid with a near-white connected component when a small patch must land on a specific spot; the tracked centre is not necessarily the visual centre.
- Look at the first and last frames of the covered interval. An effect that starts or ends abruptly reads as an edit.
- Look at a frame just outside the interval to confirm the transition is clean.
- Confirm the frames before the interval are visually identical to the source; the re-encode must not shift them. Compare by exact frame index with `cv2.VideoCapture`, not by `-ss` seeking, which can land on neighbouring frames in differently-keyed encodes.

## Pitfalls recorded from earlier rounds

- A white core produces a bright rectangle edge when its row/column order is transposed. Keep the core array's rows and columns matching the image's rows and columns.
- `cv2.imwrite` expects BGR. Feeding it RGB data shifts the whole frame blue.
- `cv2.connectedComponentsWithStats` returns stats as `[x, y, w, h, area]`. Unpacking them in any other order silently drops every component once an area filter is applied.
- ORB homographies map source→target. To translate a coordinate from a screenshot back into the video frame, invert the matrix.
- Tracking forward from the first frame drifts or dies when the target is briefly occluded. Seed from a reference frame and track in both directions.
- Low-texture targets (bare skin, satin) make template tracking wander hundreds of pixels even within a single shot, and costume changes break it entirely. When the subject is essentially static, lock the centre with a full-frame template: `--region 0,0,WIDTH,HEIGHT` makes the match output 1×1, so the centre is always `(WIDTH/2, HEIGHT/2)`. Move the light to the target with `--offset DX,DY`. Recompute the zone multipliers from `rx = zone-width × WIDTH` and `ry = zone-height × HEIGHT`, since the tracked box is now the whole frame.
- The concat output has no declared frame rate. Without an explicit `-r` on the encoder, a 24 fps source is delivered at 25 fps with a different frame count. Always re-probe `r_frame_rate`, `nb_frames`, and `duration` against the source; the script now pins the encoder to the probed fps.

## Pink Korean holy-light look

`--sticker-look korean` owns its own light-shaped blur and whitening, so the knob ladder above (`--blur`, `--zone-*`, `--plateau`, `--core`, `--milk`, `--sigma-*`) does not apply. Tune `--holy-size`, `--glow-scale`, `--glow` and `--offset` instead, and give it a single region: the two lobes already cover both sides. `--sticker-compact` switches from the wide three-lobe glow to the two small hip lobes; omitting it restores the wide coverage.

Recorded on the 720×1280 / 30 fps costume-change clip, where the user first rejected 范围太大:

| Setting | Lobe opacity | Centre opacity | Centre skirt mean | Waist y740–830 diff | Lower thigh y1150–1260 diff |
|---|---|---|---|---|---|
| source | — | — | 36 | — | — |
| wide (three lobes) | ~0.91 | 0.86 | 212 | 28.9 | 70.9 |
| compact (two lobes) | 0.87 | 0.35 | 113 | 4.0 | 4.9 |

The compact setting also leaves the top of the light at zero opacity, so the waist stays clean. Marked-hip ROI standard deviation went 60.9 → 25.0 on the delivered clip and 60.7 → 24.7 on a fresh end-to-end run of the skill, which is the number to reproduce when porting the look to another clip.

Rules learned while building the look:

- A single ellipse missed the two hip wings; a superellipse with a hard core read as a white rectangle card. Overlapping Gaussian lobes (wide) or smooth superellipse lobes (compact) are the shapes that worked.
- Keep the lettering on its own RGBA layer at full opacity and fade only the small decorations with the light. Fading everything made the middle of the text translucent once the lobes shrank and left it over a dark skirt.
- Blur only inside the light (`weight = clip(alpha × 1.12)`), then whiten with `alpha`, then composite the decal. Blurring the whole lower half first flattened the garment and the background.
- Map red-box screenshots back to source pixels with a feature homography. The player chrome, white borders and filename strip make a plain width/height ratio wrong; on this clip the scale was 3.4039 with 127 inliers.
- For a static subject, `--region 0,0,WIDTH,HEIGHT --offset 0,DY` locks the centre exactly, which is more stable than tracking a low-texture hip patch. Recompute `DY` for a different frame height: the reference used `centre_y − HEIGHT/2 = 995 − 640 = 355`.
- `--holy-size auto` derives `rx = 0.60 × width`, `ry = 0.185 × height`. When the user asks for a smaller patch, lower `--glow-scale` (or `--holy-size`) rather than re-enabling the zone blur; that only adds a second, differently shaped blur.
