# Measuring a fixed sticker rectangle

Measure from the original video frame at native dimensions. Extract frames with `ffmpeg`, open them at 100% when possible, and record the first and last pixel columns and rows belonging to the sticker. Confirm the same edges at representative timestamps. For the current example, the repeated hard edges were detected at approximately `x=256`, `x=823`, `y=1261`, and `y=1848`, which becomes a `568×588` rectangle when using top-left origin and exclusive right/bottom bounds.

A screenshot annotation is not a source coordinate system. If a screenshot is resized, translated, padded, or contains a red guide, convert it only as visual guidance and re-measure the original video.
