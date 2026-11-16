# Runtime And Masking

## Runtime discovery

Before processing, check the existing environment rather than installing blindly:

```bash
command -v python3
command -v ffmpeg
command -v ffprobe
python3 -c 'import cv2, torch; print(cv2.__version__, torch.__version__, torch.backends.mps.is_available())'
```

Search likely local model locations without scanning unrelated disks. Reuse an existing LaMa checkpoint such as `big-lama.pt` when it is present. A checkpoint alone is not enough: confirm that the installed loader and its configuration can open it. If the loader, PyTorch, or checkpoint is missing, report the exact missing component before installing or downloading anything.

Use Apple MPS when the local runtime supports it. Keep CPU fallback bounded and warn about the longer processing time. Keep model initialization outside the per-frame loop.

## Mask construction

The mask is defined in source-video pixels with top-left origin. It should include the target's visible ink or shape, outline, alpha edge, glow, shadow, and bright particles, with the smallest extra margin needed to avoid a visible halo. It must exclude nearby hair, hands, clothing, and background details that are not part of the target.

For a fixed overlay, validate one mask across frames at the beginning, middle, motion changes, and end. For a moving or scaling overlay, define keyframes or a tracked shape and inspect each change. Do not reuse coordinates from another video.

When only a screenshot contains the annotation, derive the mask from the clean source video. Never include red boxes, arrows, circles, player controls, or other screenshot UI in the mask.

## Local repair

Use the mask to crop a context region around the target and run LaMa only on that crop. The crop may be resized for model input, but the final frame must retain the source dimensions. Composite the inpainted crop through the mask over the untouched source frame. This prevents a local model from changing unmasked parts of the scene.

For text over a person or detailed clothing, test frames with the most occlusion first. A smooth background can tolerate a smaller context crop; hair, hands, fabric edges, and moving limbs need more context and usually a carefully shaped mask. If a target changes size or becomes blurred, the mask should follow its visible halo rather than using one oversized rectangle.

## Video preservation

Use the source frame timestamps when the source is variable-frame-rate. Do not silently convert VFR to CFR. Preserve rotation metadata, pixel format, color range, and transfer characteristics where the encoder permits. Use a temporary directory unique to this job and remove intermediate frames after a successful export or a cancelled job.

For comparison output, scale both branches to a common display size without changing the repaired master. Keep the original branch untouched, put original on the left and repaired on the right, and map exactly one audio stream from the source.
