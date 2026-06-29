# Face-Matching Results (measured)

First **measured** accuracy for the face-matching engine (SFace embeddings +
`compare()`), on the standard **LFW** benchmark.

## Setup

- **Dataset:** LFW (Labeled Faces in the Wild) — multifaces subset, installed via
  `scripts/install_lfw_face_pairs.py`.
- **Identities:** 70 (each with a reference image + selfies).
- **Comparisons:** 210 genuine pairs (same person), 560 impostor pairs (different people).
- **Harness:** `scripts/evaluate_face_matching.py`.

## Results

| Metric | Value |
| --- | --- |
| Genuine score mean (same person) | **0.826** |
| Impostor score mean (different people) | **0.546** |
| Equal-error-rate point | threshold **0.64** → FAR **1.07%**, FRR **0.95%** (≈ 1% EER) |
| At `min_face_match_score = 0.68` | **FAR 0.0%**, FRR **1.43%** |
| At `face_login_threshold = 0.72` | **FAR 0.0%**, FRR **1.90%** |

**Reading it:** FAR = impostors wrongly accepted; FRR = genuine users wrongly
rejected. At the current 0.68 threshold the engine accepts **no impostors** in
this set and wrongly rejects only **~1.4%** of genuine users — a strong,
security-leaning operating point. The equal-error rate is about **1%**.

## Interpretation

- The current **0.68 threshold is well chosen** — biased toward security (0% FAR)
  at a small FRR cost, which is appropriate for eKYC.
- The matching engine separates genuine vs impostor cleanly (0.83 vs 0.55 mean).

## Honest caveats

- **LFW is unconstrained celebrity photos**, not the eKYC scenario of a
  **document portrait vs a live selfie** (where the document may be a printed or
  scanned photo). Cross-domain matching is harder, so the **real eKYC FRR is
  likely somewhat higher** than 1.4%. This number is the engine's intrinsic
  capability — an upper bound on what's achievable — not the end-to-end eKYC FRR.
- 70 identities / 560 impostor pairs is a solid sample but not huge; more would
  tighten the confidence interval.
- **Next:** collect genuine **document-portrait ↔ live-selfie** pairs from real
  (consented) users to measure the true end-to-end eKYC matching FRR.

## Reproduce

```bash
.venv/bin/python scripts/install_lfw_face_pairs.py --max-identities 70 --max-images 4
PYTHONPATH=backend .venv/bin/python scripts/evaluate_face_matching.py
```
