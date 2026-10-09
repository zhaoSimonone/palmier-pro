# Makeup looks

Add a look by editing `scripts/looks.py`. Keep display names in Chinese when the look is a product name.

## 轻薄暖桃妆 (`warm-peach`)

Thin warm peach makeup. Source wording: 蓝发妆造 pack “轻薄暖桃妆” / “warm peach makeup”.

Use when a generated clip lost blood in the face compared with the live-action source, or when the user asks for 红晕 / 美颜 without a new identity.

| Layer | Role | Strength 1.0 peak add (BGR) |
|---|---|---|
| warmth | Correct cold/pale generated skin | `(1.0, 3.2, 8.0) * 0.55` |
| blush | Peach on the apples, plus a little nose-wing | `(5, 12, 44) * 0.62` |
| lips | Coral, weaker than blush | `(4, 6, 30) * 0.48` |
| lids | Faint peach wash | `(0, 5, 16) * 0.30` |
| smooth | Light bilateral mix on the face | `0.18` |

Geometry is relative to inter-eye distance. Far-cheek opacity falls off with yaw so a profile does not stamp a red disc on the hidden side. A skin gate blocks blue hair and black fabric.

Do not treat this as contour, heavy lipstick, or eyeliner redraw.

## Adding a look

Copy `warm-peach` in `scripts/looks.py`, change `id`, `display_name`, aliases, and the layer gains. Keep one look per coherent product name. Preview stills before adding a second look to the skill.
