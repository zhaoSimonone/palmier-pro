# Implementation notes

## What the prior workflow used

1. `ffprobe` to establish duration, video dimensions, frame rate, and audio stream presence.
2. Frame extraction and contact sheets to inspect the transformation point and motion.
3. A user-supplied GIF as an animated overlay rather than a generated censor shape.
4. PIL/OpenCV to decode GIF frames, remove only edge-connected white background pixels, and preserve enclosed white artwork.
5. A pixel-coordinate keyframe path for the overlay center. The position was interpolated and lightly smoothed; the overlay width and height were deliberately kept constant after the user requested that behavior.
6. RGBA PNG overlay frames composited by FFmpeg, with source audio mapped and copied when possible.
7. Output metadata checks and sampled-frame inspection, especially the first covered frame, motion turns, and final frames.

## Why not use a plain blur or glow

A glow or semi-transparent blur changes the appearance but may leave the covered detail legible. A user-provided opaque animated artwork is a stronger cover when the user explicitly asks for it. Keep the overlay geometry separate from the visual artwork so size and motion can be adjusted without changing the source asset.

## Coordinate convention

Coordinates are source-video pixels with origin at the top-left. `x` and `y` in the keyframe file refer to the overlay center. The frame renderer places the top-left corner at `(x - width / 2, y - height / 2)`.

## Lessons from coverage corrections

- Inspect the whole video before selecting intervals. A close-up can reappear later; do not stop coverage merely because the first close-up ends.
- Map screenshots to source pixels after excluding player chrome, padding, and scaling. Do not reuse coordinates from another video.
- Track the selected region, not the nearest body landmark. Use denser keys around camera zooms, cuts, movement reversals, and the final visible frames.
- Validate frame boundaries at native frame rate; sparse contact sheets cannot prove complete coverage. Describe checks honestly rather than claiming every frame was verified.
- End overlays at a scene cut or black frame when the target disappears; do not leave a floating sticker over the ending.
- Keep sticker canvas size constant when requested, but inspect every animation frame: artwork itself may still change silhouette.
- A watermark includes decorative wings, glow and text, not just its center. Alpha holes may reveal letters even if the sticker's bounding box encloses the target.
- Export from the original source into a new filename; preserve previous outputs and show the delivered video using an absolute-path Markdown media embed.
