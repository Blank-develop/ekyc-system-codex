# Hand Gesture Guide

Simple reference for every hand gesture challenge in the Kyron eKYC verification flow.

How the challenge works:

1. Each verification session randomly assigns 3 gestures. At least 2 are always from the easy set.
2. Open the full-screen camera and show one hand.
3. Move your hand inside the circle shown on screen.
4. Make the requested gesture and hold it until the gold ring completes.

Tips for a smooth pass:

- Use good lighting and keep your whole hand visible.
- Face your palm toward the camera.
- Hold the gesture steady; quick movements reset the progress ring.

## Counting gestures (easy)

| Sign | Gesture | How to do it |
| --- | --- | --- |
| 1️⃣ | Show 1 | Raise one finger. |
| 2️⃣ | Show 2 | Raise two fingers. |
| 3️⃣ | Show 3 | Raise three fingers. |
| 4️⃣ | Show 4 | Raise four fingers. |
| 5️⃣ | Show 5 | Show all five fingers, open palm. |
| ☝️ | Point up | Point one finger up. |
| ✌️ | Peace sign | Raise index and middle finger in a V. |
| ✌️ | Victory sign | Same as the peace sign: index and middle finger in a V. |

## Palm and fist gestures (easy)

| Sign | Gesture | How to do it |
| --- | --- | --- |
| ✋ | Open palm | Show your open hand, fingers spread. |
| 🖐️ | High five | Show your open hand like a high five. |
| ✋ | Stop sign | Show your open hand like a stop signal. |
| ✊ | Fist | Close your hand into a fist. |

## Thumb and pinch gestures (easy)

| Sign | Gesture | How to do it |
| --- | --- | --- |
| 👍 | Thumb up | Make a fist and point your thumb up. |
| 👌 | OK sign | Touch your thumb and index fingertip in a ring; keep other fingers up. |
| 👌 | Pinch | Touch your thumb and index fingertip together. |
| 👌 | Small OK | Same as the OK sign. |
| 🤌 | Pinched fingers | Bring all fingertips together, pointing up. |
| L | L shape | Extend your thumb and index finger to form an L. |

## Trickier gestures (each session includes at most one)

| Sign | Gesture | How to do it |
| --- | --- | --- |
| 👎 | Thumb down | Make a fist and point your thumb down. |
| 🤘 | Rock on | Raise index and pinky; fold middle and ring fingers. |
| 🤟 | I love you | Raise thumb, index, and pinky; fold middle and ring fingers. |
| 🤙 | Call me | Extend thumb and pinky; fold the other fingers. |
| 🤞 | Crossed fingers | Cross your index and middle fingers. |

## Where this is defined

- Prompt list and easy-weighted sampling: `backend/app/services/session_store.py` (`HAND_PROMPTS`, `TRICKY_HAND_GESTURE_IDS`, `sample_hand_prompts`).
- Detection and matching: `frontend/src/components/HandGestureCapture.tsx` (`classifyGesture`, `matchesGesture`, `gestureVisual`).
- Sampling guarantees are covered by `backend/tests/test_session_store.py`.
