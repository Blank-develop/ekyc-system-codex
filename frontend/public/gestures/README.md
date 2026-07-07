# Hand-gesture reference images

Drop your generated hand-gesture images here as `<gesture_id>.png`. The app loads
each one from `/gestures/<gesture_id>.png` and **falls back to an emoji** if the
file is missing, so the flow keeps working while you add images.

The API also advertises the path to partners as `image_url` on each hand-gesture
challenge (see `docs/partner-api-integration-guide.md`).

## Expected files (23 gestures)

| Gesture ID | Prompt | File to add |
| --- | --- | --- |
| `one` | Show 1 | `one.png` |
| `two` | Show 2 | `two.png` |
| `three` | Show 3 | `three.png` |
| `four` | Show 4 | `four.png` |
| `five` | Show 5 (open palm) | `five.png` |
| `point` | Point up | `point.png` |
| `peace` | Peace sign | `peace.png` |
| `victory` | Victory sign | `victory.png` |
| `open_palm` | Open palm | `open_palm.png` |
| `high_five` | High five | `high_five.png` |
| `stop` | Stop sign | `stop.png` |
| `fist` | Fist | `fist.png` |
| `thumb_up` | Thumb up | `thumb_up.png` |
| `ok` | OK sign | `ok.png` |
| `pinch` | Pinch | `pinch.png` |
| `small_ok` | Small OK | `small_ok.png` |
| `rock_on` | Rock on | `rock_on.png` |
| `call_me` | Call me | `call_me.png` |
| `thumb_down` | Thumb down | `thumb_down.png` |
| `i_love_you` | I love you | `i_love_you.png` |
| `l_shape` | L shape | `l_shape.png` |
| `pinched_fingers` | Pinched fingers | `pinched_fingers.png` |
| `crossed_fingers` | Crossed fingers | `crossed_fingers.png` |

## Tips
- **Format:** PNG (transparent background looks best) or WebP — rename to `.png`
  or update the loader if you prefer another extension.
- **Size:** export small — around **256×256 px**, compressed. 23 icons should total
  well under 1 MB.
- **Naming:** the filename must exactly match the gesture ID above (lowercase,
  underscores). A wrong/missing name simply shows the emoji fallback.

## How the current images were made

Regenerate with `scripts/build_gesture_images.py`. 20 of the 23 use **Google Noto
Emoji** color artwork (medium-light skin tone) — realistic, gradient-shaded flat
hands. Three gestures have no Unicode emoji (`three`, `four`, `l_shape`) and are
drawn as a matching skin-gradient SVG.

**Attribution:** hand artwork © the Noto Emoji project, licensed under the
**Apache License 2.0** (https://github.com/googlefonts/noto-emoji). To swap in your
own brand illustrations, just drop replacement PNGs here with the same filenames.
