# Region detection and tracking

How the script finds the target, follows it, and keeps the blur on the right body part.

## Coordinate convention

All coordinates are source-video pixels with the origin at the top-left. `x` grows right, `y` grows down. The script works on decoded frames at the video's native resolution, so a coordinate taken from a scaled screenshot must be rescaled first.

## Skin segmentation

The default HSV window isolates bare skin while rejecting the garments that usually surround it:

| Channel | Range | Why |
| --- | --- | --- |
| H | 5 – 34 | skin tones; rejects red cloth (H ≈ 1) and gold armour (H ≈ 15 but low S) |
| S | 85 – 180 | skin sits around S ≈ 92–105; white satin is S ≈ 4–10, gold armour S ≈ 50 |
| V | 120 – 250 | keeps the shadowed edge of a limb from becoming a separate component |

The mask is then cleaned with a 7×7 morphological open and a 15×15 close, which removes speckle and closes the small holes left by fabric edges.

Override the window with `--hue`, `--sat`, `--val` when the footage has a colour cast that pushes skin outside the default range. Use `--hue 0,40` to widen the hue span for very warm or very cool lighting, and raise `--sat` only if the skin is genuinely desaturated.

## Picking a seed point

The seed is a single point that must land **inside** the target, not on its edge and not on a neighbouring part. The script grows the seed into the connected component that contains it, so a seed on a boundary can latch onto the wrong blob.

1. Extract one frame from the middle of the interval you plan to cover.
2. View it and pick a point in the middle of the exposed area.
3. Pass it as `--seed X,Y`.

For a thigh that is a triangle, pick a point in the wide lower part, not the apex: a narrow apex produces a small component that the tracker loses as soon as the limb rotates.

## Turning a red box on a screenshot into source pixels

A screenshot is not the video. It carries player chrome, surrounding desktop, and its own scale, so its pixel coordinates are meaningless in the source frame. Map them through a homography:

1. Crop the screenshot down to the video picture only — drop the control bar and everything outside the player's viewport.
2. Match the cropped screenshot against the decoded frames with SIFT and RANSAC, then map the red box's four corners through `H`. The result is a source-pixel rectangle.

**Match against every frame, not just the first one.** A screenshot is one instant of a moving subject, so the homography that fits it changes with the pose. Compute it for a sample of frames across the clip and pick the frame with the most inliers; neighbouring frames with a similar inlier count confirm the answer. On one real clip the screenshot matched frame 34 with 369 inliers while frame 0 gave only 78 — and the two disagreed by 45 px on the target box. Low inlier counts and boxes that jump around between candidate frames are the signature of a non-rigid mismatch, not of a bad crop.

**Then set `--reference-frame` to that frame.** The tracker pins the box at the reference frame and expands from there in both directions, so the reference frame is where the box is *known* to be correct. Leaving it at the interval midpoint places the box on the target at a moment when the subject may have moved somewhere else entirely. Measured on the clip above, using the correct frame instead of the midpoint moved the tracked box off the chest in the middle of the interval and cut the ROI standard-deviation drop from 57% to 49%.

## Keeping regions apart

A thigh, a hand resting on the hip, and the bare midriff are frequently one connected skin region in the mask. The tracker then measures the whole blob and centres the blur between the legs, leaving the actual target exposed.

The script separates them with a **band**: a column range that is zeroed out of the mask before the connected-component analysis, so the parts on either side of it become different components.

Note what "band" actually does: it **removes every pixel in that column range from the mask**, not just a dividing line. A body part that lies entirely inside the band disappears from the mask and stops dragging the component's bounding box. That is often exactly what you want — putting the band over a hand that is touching the thigh removes the hand and leaves a clean thigh component. It also means a band that is too wide will clip the target itself: any part of the thigh that reaches past the band's edge gets its columns cut off, so the tracked bounding box shrinks and the blur zone follows the clipped shape.

- Give `--band X1,X2` explicitly when you know where the gap between the two regions is. In the reference clip the gap sits at columns 495–705, which also covers the hand resting on the hip.
- Without `--band`, the script uses the middle half of the gap between the two seeds, which is a reasonable default when the two targets are symmetric and separated.

If the two regions touch or overlap in the frame, `--band` cannot separate them without clipping one of them. Track one of them with `--region X,Y,W,H` instead, which uses template matching and ignores the skin segmentation entirely.

## Tracking

`--seed` mode runs a windowed connected-component search:

- The component containing the seed is located in the **reference frame**, which is the middle frame of the interval unless `--reference-frame` says otherwise.
- Tracking then runs **forwards and backwards** from that reference frame. Seeding from the first frame and only tracking forwards fails whenever the target is briefly occluded or poorly segmented at the start.
- Each step searches for the component nearest the previous frame's centre, inside a window that is the previous bounding box grown by a margin. A small search radius keeps the tracker on the same body part even when a larger one would jump across the body.
- When no component is found, the previous box is carried forward, so the track never has holes.

`--region` mode instead matches a fixed-size patch of the reference frame with normalised cross-correlation, which follows a target that is not skin — a hand, a garment edge, an object, a shadowed cleavage.

Three knobs keep that match honest:

- `--track-pad N` adds N pixels of context around the region **for matching only**; the reported box keeps the requested size, so the blur footprint stays exactly where the user pointed. Use it whenever the target is smooth skin or a shadow with no texture of its own — normalised correlation needs *some* structure to anchor on, and bare skin has almost none.
- `--search-radius R` caps the per-frame displacement of the tracked centre. The search window is `centre ± (template_half + R)`. Keep it tight: a loose window lets the template jump onto a similar-looking patch elsewhere on the body.
- `--min-score S` holds the previous position when the best match scores below S, so an implausible frame produces a still box rather than a wild jump.

A `--region` box is a rectangle in source pixels: `X,Y,W,H`, with `X,Y` at the top-left. To convert a red box drawn on a screenshot, first remove the player chrome and the surrounding desktop, then map the four corners through the homography between the screenshot and a decoded frame — see the pitfalls in [tuning.md](tuning.md).

### When the region is a shadow rather than skin

Skin segmentation classifies a shaded cleavage, the underside of a breast, or a shadow under an arm as **background**, so `--seed` mode will not find it no matter how the thresholds are tuned. When the user's red box sits on a shadow, go straight to `--region`: a rectangle the user drew is a better description of the target than any colour rule.

## Temporal smoothing

The tracked centre is smoothed along the time axis with a Gaussian of `--smooth` (default 2.0). Segmentation jitter of a few pixels per frame is normal and is very visible as a wobbling blur edge; smoothing removes it without visibly lagging behind real motion. Raise it for fast camera moves, lower it if the blur visibly trails a sudden movement.

## What the blur geometry means

The tracked bounding box is turned into a feathered ellipse:

- `rx = --zone-width × box_width`, `ry = --zone-height × box_height`. Because the ellipse is centred on the box centre, it spans `zone-width × box_width` in total — so a multiplier of 0.95 gives an ellipse just under twice the width of the skin region, and a multiplier of 1.5 gives one three times as wide. The default 0.95 / 0.85 keeps the feathered rim just outside the target instead of out on the neighbouring garment.
- The mask is 1.0 inside `plateau × r` and falls to 0 at `r`, using a smoothstep so there is no visible boundary. A high plateau (the default 0.78) makes the fully blurred core large relative to the feathered rim, which reads as an overall softening rather than a pasted patch.
- `sigma = --blur × rx`, clamped to `[--sigma-min, --sigma-max]`. Expressing sigma as a fraction of the zone radius keeps the blur proportional when the subject moves closer to the camera. The clamp matters as much as the ratio: the kernel spreads about `3 × sigma`, so a large sigma reaches outside the zone and drags dark neighbours into the blur.
- `--milk` adds a small brightness lift inside the blur, which reads as frosted glass. Keep it small; a large lift creates the bright hotspot that users reject.
