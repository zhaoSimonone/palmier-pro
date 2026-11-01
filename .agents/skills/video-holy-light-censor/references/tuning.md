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
| `--reference-frame` | middle | frame used to seed the tracking. Set it to the frame the user's box was drawn on, not the interval midpoint — the tracker pins the box there. |
| `--min-area` | auto | smallest skin blob in pixels that may be tracked. Auto derives it from the frame size (about 0.06% of the frame area, floored at 400 px). Raise it when a small skin-coloured accessory is being picked up as the target. |
| `--hue` / `--sat` / `--val` | `5,34` / `85,180` / `120,250` | the HSV window used for skin detection. |
| `--track-pad` | 0 | extra pixels of context added around a `--region` box **for matching only**. The blur still covers the region alone. Raise it when the target is smooth skin or shadow with no texture of its own. |
| `--search-radius` | 60 | how far a `--region` template's centre may move per frame, in pixels. |
| `--min-score` | 0.0 | hold the previous position when the best template match scores below this (0–1). 0 accepts every match. |

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
| "腿变黑了" | `--sigma-max` down | The blur is reaching into a dark neighbour. |
| "糊块飘了 / 跟不上" (region mode) | `--track-pad` up, `--search-radius` up | The template had no context to match on and the window was too tight to follow the motion. |
| "糊块卡住不动" (region mode) | `--min-score` up | The match was below the confidence floor and the position was being held. |

Push in this order: disable the core, enlarge the zone, then deepen the blur. Deepening the blur first dissolves the body shape and is hard to undo.

## Default recipe that worked

```
--blur 0.30 --zone-width 0.95 --zone-height 0.85 --plateau 0.78 --milk 2.0 --core 0.0
--sigma-min 16 --sigma-max 26 --smooth 2.0
```

With seeds and a band chosen for the clip, this produced a soft, evenly feathered patch with no hotspot, no legible detail, and no smear on the neighbouring garment. An earlier, wider recipe (`--zone-width 1.50 --zone-height 1.08 --blur 0.20 --sigma-max 48`) hid the target too, but left a broad grey veil across the white costume and pulled the dark background into the blur; the tighter recipe above is the better starting point.

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

Use `max` over channels rather than a single channel: it is the strictest measure of "is anything still legible here".

## A veil is not a blur

A flat, semi-transparent overlay that lifts the blacks can drop the ROI standard deviation while leaving the target completely readable. The number looks good, the picture does not. This is the single most common way a censor fails while still passing a naive contrast check.

Two checks distinguish them:

1. **Look at the target.** The body outline must no longer be readable as a body part. If you can still tell it is a leg, the effect is a veil.
2. **Check the mean.** A veil that lifts the blacks raises the mean and flattens it. A real blur pulls surrounding pixels into the target and keeps the mean near the source value. A covered region whose mean has dropped by more than a few percent is absorbing dark surroundings — lower `--sigma-max` and shrink the zone.

## Checks beyond the ROI

- Compare the full frames of source and output side by side, not just the crop. A zone that is too large leaves a visible smudge on the neighbouring garment.
- Look at the first and last frames of the covered interval. An effect that starts or ends abruptly reads as an edit.
- Look at a frame just outside the interval to confirm the transition is clean.
- Confirm the frames before the interval are visually identical to the source; the re-encode must not shift them.

## Pitfalls recorded from earlier rounds

- A white core produces a bright rectangle edge when its row/column order is transposed. Keep the core array's rows and columns matching the image's rows and columns.
- `cv2.imwrite` expects BGR. Feeding it RGB data shifts the whole frame blue.
- `cv2.connectedComponentsWithStats` returns stats as `[x, y, w, h, area]`. Unpacking them in any other order silently drops every component once an area filter is applied.
- ORB homographies map source→target. To translate a coordinate from a screenshot back into the video frame, invert the matrix.
- Tracking forward from the first frame drifts or dies when the target is briefly occluded. Seed from a reference frame and track in both directions.
