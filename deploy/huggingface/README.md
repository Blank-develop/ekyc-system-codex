---
title: Kyron eKYC
emoji: 🪪
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Kyron eKYC — live demo

NIST IAL2-aligned identity verification: document proofing, active liveness,
hand-gesture challenge, selfie match, and an explainable decision — all served
from this Space over HTTPS so the camera works.

**Public demo: use sample or redacted documents only. Do not upload sensitive
real identity documents.**

Notes:
- Storage is ephemeral on the free tier; enrolled profiles reset on rebuild/sleep.
- First request after a cold start warms the face / anti-spoof models and is slower.
