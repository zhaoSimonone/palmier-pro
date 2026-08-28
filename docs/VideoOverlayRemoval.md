# Video Overlay Removal

Palmier Pro treats overlay removal as a source-video edit, not as a crop or a new text-to-video shot.

## Pipeline

1. The `remove_overlays` Agent tool validates a video asset and submits it to the configured source-video edit model.
2. The prompt asks the model to inpaint only the named non-diegetic overlay while preserving subject motion, framing, timing, color, and audio.
3. The request persists `GenerationInput.postprocess` with a versioned post-process key.
4. When the remote result is downloaded, `VideoOverlayArtifactCleaner` scans the first 48 frames for the known purple rounded-panel artifact and repairs only matching pixels on its border.
5. The original audio track is muxed back into the cleaned video before the staged file is installed in the project package.

## Why the split exists

Semantic reconstruction belongs to the video model because the pixels behind a logo or panel are unknown. The local pass is intentionally deterministic and narrow: it removes a repeatable model artifact without replacing an arbitrary region or changing unobstructed content.

## Scope and limits

- `remove_overlays` is the single user-facing entry point for this workflow.
- The original asset is never modified; the result is a new generated asset.
- A result without the known artifact is passed through unchanged.
- The current artifact cleaner targets the identity-transform portrait panel observed during validation. Unsupported transforms or unrelated artifacts are left for the model result rather than guessed locally.
- New deterministic repairs must use a new `postprocess` key and add focused detection and persistence tests.
