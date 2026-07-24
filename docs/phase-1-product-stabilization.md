# Phase 1: Product Stabilization

## Objective

Turn the current eKYC prototype into a measurable, reproducible product baseline. This phase does not claim NIST IAL2, ISO, PAD, privacy, or legal certification. It creates the evidence and release controls needed before formal validation.

## Scope

- Passport and Lao ID capture, OCR, fraud signals, and decisions.
- Active face liveness and replay screening.
- Hand gesture challenges.
- Selfie passive liveness and document-to-selfie face matching.
- Face enrollment and returning-user face login.
- API, web frontend, TypeScript SDK, and Flutter SDK compatibility.

## Milestone 1: Reproducible Baseline

Status: **implemented; the gate result must be reviewed for every release**.

- New verification sessions return `engine.pipeline_version`, `engine.decision_policy_version`, and `engine.build_sha`.
- `npm run phase1:gate` compiles the backend, runs backend tests, builds the frontend, inventories evaluation datasets, and writes `outputs/phase1/release-gate.json`.
- Existing `pending`, `passed`, and `rejected` API states remain unchanged to avoid silently breaking SDK clients.

## Release Exit Criteria

1. The release gate reports `passed` from a clean, tagged commit.
2. Backend tests and the frontend production build pass without retries.
3. API and all SDKs parse the same versioned verification result.
4. Decision thresholds and model files are fixed and identified for the release.
5. Test identities are split by person and session to prevent calibration/evaluation leakage.
6. Every module has a confusion matrix and p50/p95 latency report on target devices.
7. Known false accepts and false rejects have an owner, severity, and disposition.
8. Build rollback and database migration rollback have been exercised.

## Measurement Contract

Report counts and confidence intervals, not accuracy alone.

| Module | Required metrics | Important slices |
| --- | --- | --- |
| Document classification/OCR | acceptance rate, field exact match, MRZ read rate, false reject rate | country, type, camera, rotation, glare, blur |
| Document fraud/recapture | attack pass rate, genuine false reject rate, precision/recall by attack | print, photocopy, screen, crop/replace, text edit |
| Active liveness | attack pass rate, genuine completion rate, retry rate, p50/p95 latency | phone/tablet/laptop replay, lighting, glasses, device |
| Selfie PAD | APCER, BPCER, ACER for reporting, p50/p95 latency | print, screen photo, video replay, mask, device |
| Face matching/login | FNMR at fixed FMR, FMR, failure-to-enroll/acquire, p50/p95 latency | demographic/device slices, pose, glasses, lighting |

Dataset size is not a substitute for independence or diversity. As an engineering baseline, target at least 200 genuine sessions and 100 attacks per supported attack class across multiple people and devices. Formal PAD and biometric claims require the applicable independent or accredited evaluation protocol.

## Versioned API Follow-up

The current three decision states cannot distinguish a recoverable capture problem from fraud or an inconclusive result. Add `retry` and `manual_review` only in a versioned API/SDK release with migration tests. Until then, reason codes remain the detailed machine-readable outcome.

## Remaining Backlog

- Freeze a representative holdout set for every module.
- Generate one metrics baseline from frozen code, models, policy, and datasets.
- Calibrate thresholds on development data, never the final evaluation set.
- Run the release gate in CI for every pull request.
- Add API contract snapshots and SDK compatibility tests.
- Add model artifact hashes and signed release manifests.
- Add versioned `retry` and `manual_review` outcomes.
- Test accessibility, mobile browsers, recovery, timeouts, and interrupted networks.
- Exercise rollback, incident response, and model degradation runbooks.
