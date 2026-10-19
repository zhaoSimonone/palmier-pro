# Palmier Pro Skills

Project-local skills for Codex live in this directory. Each folder is one skill with a `SKILL.md` entrypoint.

## video-exact-sticker-cover

Cover a fixed rectangular sticker, watermark, or logo with an opaque block that matches the source-video bounds. Use when the sticker must be fully hidden without extra surrounding coverage. Do not use for moving objects, faces, or red-box annotations as masks.

Invoke with: `用 video-exact-sticker-cover 处理这个视频：/path/to/source.mp4`

## video-overlay-censor

Composite a user-provided GIF or PNG over a video at a fixed size, with a fixed center or keyframed tracking. Use for explicit coverage of a logo, watermark, face, or object. Do not use for automatic sensitive-content detection.

Invoke with: `用 video-overlay-censor 给这个视频加遮挡贴图：/path/to/source.mp4`

## video-face-makeup

Overlay a tracked makeup look onto a finished video, defaulting to 轻薄暖桃妆. Use for blush, 红晕, 补妆, or a thin beauty overlay. Do not use for hair or costume replacement, whole-frame grading, or sticker covers.

Invoke with: `用 video-face-makeup 给这个视频补轻薄暖桃妆：/path/to/source.mp4`
