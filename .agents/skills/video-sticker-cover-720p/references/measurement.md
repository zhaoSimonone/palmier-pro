# Measuring a fixed sticker inside a portrait video

`scripts/measure_region.py` returns a machine-checked starting point. This note explains what each signal means and
how to turn it into a rect that leaves no fringe.

## Signals the script prints

| Field | Meaning |
|---|---|
`levels.sticker` | median temporal std in the middle of the search region — the static overlay |
`levels.background` | median temporal std in the region border band — the moving scene |
`suggestedRect` | 50% crossing on every side, in source pixels |
`presence` | frame spans where the region centre barely changes vs the middle frame, i.e. where the sticker is on screen |
`gradientPeakRows/Cols` | strongest luminance steps along each axis, useful for hard edges |

Search region: frame the sticker with a 10–20% margin of *moving* background. If the margin is static wall, the
background level collapses and the script refuses with `no static rectangle found`.

## Two edge classes

**Hard edge** — native-resolution source. One pixel carries the whole step; gradient magnitude is 80–200 on a
saturated sticker, 20–50 on a muted one. Read raw pixels on both sides and take the first sticker pixel:
an edge "at row 1083" from a gradient profile means the step is between 1083 and 1084, so the sticker starts at 1084.

**Soft edge** — the clip was upscaled 2× or passed through a blur filter. The ramp spans 2–10 px and the same
sticker has lower contrast, so gradient peaks are only 20–45. The 50% crossing sits mid-ramp; covering only that
leaves a partially blended frame line. Extend outward until the temporal variance of the adjacent row/column matches
the background several pixels further away.

Worked soft-edge numbers (1076×1912 clip, upscaled, sticker x≈237–917, y≈1222–1904):

```
column  std   alpha
514     5.15  ~0.9   sticker core
515     9.50  ~0.76
516    22.42  ~0.43  crossing
517    31.96  ~0.18
518    37.12  ~0.06  fringe
519    38.69  ~0.01  background
```

Background for that column band is ≈39. Alpha is `1 - std/background`. Cover through the first column whose alpha
is indistinguishable from background noise, not through the 50% crossing.

## Ring test (the verification that catches a bad rect)

After rendering, compute temporal std on the rows/cols immediately outside each side and compare with 4–8 px
further out. If the adjacent band still reads lower, that side is short by 1–2 px:

```
row 1219  28.05   background
row 1222  25.17   short by 1 px
row 1903  11.48   short by 1 px
```

Re-render with the corrected rect; a good rect shows a flat profile across the boundary.

## Cover colour readback

`--color 58,58,58` is interpreted through the source's YUV matrix, so the decoded RGB may read 56 or 58 depending on
the clip. Verify the block's actual per-frame mean and report it instead of assuming the parameter value.

## Presence windows

A sticker can fade in, animate in, or appear only in part of the clip. Two independent checks:

- `presence` from the script (region centre vs middle frame).
- Border frames of the clip: a fully black first frame means a fade-in, so start the cover at the first frame that
  actually carries content, not at 0 — otherwise the cover paints grey onto black.

Per-rect `@START,END` windows keep a cover off frames where nothing is on screen; `--end` is exclusive at the frame
boundary, and the script converts times to inclusive frame indices with near-integer snapping.
