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

## video-holy-light-censor

Obscure a sensitive body region in a video with a tracked, feathered, pixel-level Gaussian blur (圣光遮挡). Use when the user asks to 遮挡 / 打码 / 模糊 a moving area such as 大腿, 胯部, 胸部, or 臀部. Do not use for GIF or PNG sticker overlays, fixed rectangular sticker covers, or makeup effects.

Invoke with: `用 video-holy-light-censor 遮挡这个视频大腿露出来的部分：/path/to/source.mp4`

For 白光遮挡 / 闪光遮挡 / 表情包样式遮挡, pass `--sticker-style`: it adds a feathered white light patch with hand-drawn lettering, hearts, exclamation marks and sparkles over the tracked region. `--sticker-text` changes the lettering (default `喵~`), `--glow` sets the white opacity, `--glow-scale` sets how far the halo spreads. The default pipeline remains a pure blur when the flag is absent.

Invoke with: `用 video-holy-light-censor 给这个视频加表情包样式的白光遮挡：/path/to/source.mp4`

For a change-outfit clip that needs the same treatment in several scenes, repeat `--segment "start=..;end=..;region=X,Y,W,H;offset=DX,DY;smooth=.."`. Each segment keeps its own interval, tracking rectangle, offset and smoothing while sharing the look parameters, and the video is encoded only once.

Invoke with: `用 video-holy-light-censor 按相同方式把这个视频 Bunny 段的胸部也遮挡一下：/path/to/source.mp4`

For 粉色韩文圣光 / 韩国综艺圣光贴纸 / 白色圣光加粉色文字, pass `--sticker-look korean`: overlapping white light lobes plus pink hand-lettered Hangul (`너무 귀여워`), with quotation marks, exclamation marks, hearts and sparkles. It lives in `scripts/korean_holy_light.py` and reuses the same tracking, interval and encoding pipeline. Add `--sticker-compact` for the approved 只遮大腿根部及两侧 variant — two small lobes that leave the centre costume visible — and tune the footprint with `--holy-size`, `--glow-scale` and `--glow`. Lettering needs a Korean handwriting font (`NanumScript.ttc`).

Invoke with: `用 video-holy-light-censor 给变装后的片段加粉色韩文圣光，只遮大腿根部及两侧：/path/to/source.mp4`

When two marked boxes are misaligned or the subject sways, use `--holy-lobes=DX,DY,RX,RY;...` for per-lobe geometry and `--track-file` for a per-frame centre; put the centre off-frame on shots where the target is absent (for example a face close-up). See `video-holy-light-censor/references/tuning.md` for a worked example.

Invoke with: `用 video-holy-light-censor 按截图两个红框加粉色韩文圣光，只遮大腿两侧，人物会左右移动：/path/to/source.mp4`

## video-sticker-cover-720p

Hide a fixed anime or photo sticker burned into a portrait video and export a 720p MP4 in one encode. Use when a clip is rejected by a generation platform (Seedance / CapCut) because of the sticker, or the user asks 遮挡贴图并生成720p. Ships a temporal-variance measurement helper for the sticker rectangle and a single-pass cover+scale renderer. Do not use for moving overlays, faces, inpainting, or plain re-encoding.

Invoke with: `用 video-sticker-cover-720p 遮挡这个视频的动漫贴图并生成720p：/path/to/source.mp4`
