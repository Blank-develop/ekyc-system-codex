# Security Test Cases — Suite A (Access Control & Data Protection)

**Date:** 2026-06-28
**Tester:** banku
**System:** Kyron eKYC (FastAPI backend, SQLAlchemy profile store)
**Build under test:** `main` after PR #13 (admin-endpoint lockdown)

## Scope

Today's security hardening and verification:

1. **A1–A5** — Profile admin endpoints (`/api/profiles`) protected by a
   fail-closed admin-token guard.
2. **A6** — Automated regression tests for the guard.
3. **A7** — Removal of real personal data (PII) from the data store.
4. **A8** — Public demo (Hugging Face) endpoint locked.
5. **A9** — Verification flow unaffected by the change (no regression).

## Code under test

- Guard + routes: `backend/app/api/routes.py` (`require_admin`)
- Setting: `backend/app/core/config.py` (`LALIGENCE_ADMIN_API_TOKEN`)
- Tests: `backend/tests/test_admin_endpoints.py`

## Environment

| Target | How it was tested |
| --- | --- |
| Local instance (token enabled) | `uvicorn` on `127.0.0.1:8099` with `LALIGENCE_ADMIN_API_TOKEN=demo-secret-123` |
| Local prod build via tunnel (no token) | Cloudflare quick tunnel → local `:8090` |
| Public demo | Hugging Face Space `banku1212-kyron-ekyc.hf.space` |

---

## Test cases & results

> Status legend: **PASS** = observed result matched expected.

### A1 — Admin endpoint disabled when no token is configured
- **Objective:** Without `LALIGENCE_ADMIN_API_TOKEN`, profile endpoints must be unreachable (fail-closed).
- **Precondition:** Server running with no admin token set (public demo default).
- **Steps:** `GET /api/profiles`
- **Expected:** HTTP `403`, body `"Admin endpoints are disabled..."`
- **Actual:** HTTP `403`, `{"detail":"Admin endpoints are disabled. Set LALIGENCE_ADMIN_API_TOKEN to enable them."}`
- **Status:** **PASS**

### A2 — Reject request with no admin-token header (token configured)
- **Objective:** With a token configured, requests missing the header are rejected.
- **Precondition:** `LALIGENCE_ADMIN_API_TOKEN=demo-secret-123`.
- **Steps:** `GET /api/profiles` (no `X-Admin-Token` header)
- **Expected:** HTTP `401`.
- **Actual:** HTTP `401`, `{"detail":"Invalid or missing admin token."}`
- **Status:** **PASS**

### A3 — Reject request with wrong admin token
- **Steps:** `GET /api/profiles` with `X-Admin-Token: wrong-token`
- **Expected:** HTTP `401`.
- **Actual:** HTTP `401`, `{"detail":"Invalid or missing admin token."}`
- **Status:** **PASS**

### A4 — Allow request with correct admin token
- **Steps:** `GET /api/profiles` with `X-Admin-Token: demo-secret-123`
- **Expected:** HTTP `200` + profile list JSON.
- **Actual:** HTTP `200` + `{"profiles":[...]}`
- **Status:** **PASS**

### A5 — Delete endpoints guarded the same way
- **Objective:** `DELETE /api/profiles` and `DELETE /api/profiles/{user_id}` use the same guard.
- **Steps:** `DELETE /api/profiles` with and without a valid token.
- **Expected:** `403` when no token configured; `401` without header; `200` with correct token.
- **Actual:** Matches expected (covered by guard + A6 tests).
- **Status:** **PASS**

### A6 — Automated regression tests
- **Objective:** Guard behaviour is covered by repeatable tests.
- **Steps:** `pytest backend/tests/test_admin_endpoints.py -v`
- **Expected:** All pass.
- **Actual:** `2 passed` (`test_profiles_disabled_when_no_token`, `test_profiles_require_matching_token`). Full suite: **75 passed**.
- **Status:** **PASS**

### A7 — Remove real PII from the data store
- **Objective:** No real identity records remain reachable in the profile store.
- **Precondition:** Store seeded with 3 real test profiles (real passports + face templates).
- **Steps:**
  1. Stop the running backend (clear in-memory cache).
  2. Delete the legacy seed file `backend/data/face_profiles.json` (master copy that re-seeds the DB).
  3. `profile_store.delete_all()` to clear SQLite rows.
  4. Re-check from a fresh process and via `sqlite3`.
- **Expected:** Profile count `0`, and it stays `0` (no re-seed).
- **Actual:** Before: `3`. After delete + JSON removal: fresh process `0`, `sqlite3 SELECT count(*)` → `0`. Stays `0`.
- **Status:** **PASS**
- **Note (finding):** Deleting DB rows alone did **not** work — the store re-seeded from `face_profiles.json` each time the DB was empty. The JSON was the true source of the persisted PII (it also held face embeddings in plaintext).

### A8 — Public demo (Hugging Face) endpoint locked
- **Objective:** The hosted demo no longer exposes profiles.
- **Steps:** `GET https://banku1212-kyron-ekyc.hf.space/api/profiles`
- **Expected:** HTTP `403` (after the Space rebuilds from `main`).
- **Actual:** HTTP `403`, `{"detail":"Admin endpoints are disabled. Set LALIGENCE_ADMIN_API_TOKEN to enable them."}`
- **Status:** **PASS**

### A9 — Verification flow unaffected (no regression)
- **Objective:** The guard does not break normal verification.
- **Steps:** `POST /api/verifications` with a `user_id`.
- **Expected:** HTTP `200` + session JSON.
- **Actual:** HTTP `200` + session created. Also confirmed `POST /api/face-login` returns `matched: false`, `profile: null` after the PII purge.
- **Status:** **PASS**

### A10 — Document number is masked
- **Objective:** The document-number masking used in unauthenticated face-login responses hides the full number.
- **Steps:** `pytest backend/tests/test_face_login_redaction.py::test_mask_document_number`
- **Expected:** `PA0377243` → `PA•••••43`; short values fully masked; `None` → `None`.
- **Actual:** `PA0377243` → `PA•••••43`, `AB12` → `••••`, `None` → `None`.
- **Status:** **PASS**

### A11 — Face-login redacts sensitive PII (unauthenticated)
- **Objective:** On a match, the unauthenticated face-login response must not expose full passport PII.
- **Precondition:** `LALIGENCE_FACE_LOGIN_EXPOSE_PII` unset (default = redacted).
- **Steps:** `pytest backend/tests/test_face_login_redaction.py::test_redact_profile_drops_sensitive_pii`
- **Expected:** full name, last name, date of birth, and expiry dropped; document number masked; first name, nationality, age kept for the returning-user UX.
- **Actual:** `full_name/last_name/date_of_birth/passport_expiry = None`; `passport_number = PA•••••43`; `first_name = Chilanhouth`, `nationality = LAO`, `age = 24`.
- **Status:** **PASS**
- **Note:** Full PII is only returned when `LALIGENCE_FACE_LOGIN_EXPOSE_PII=true` (trusted/authenticated deployments). 77/77 backend tests pass with the change.

### A12 — Face-login per-client throttle
- **Objective:** A single client cannot make unlimited face-login attempts (brute-force / face harvesting).
- **Precondition:** Per-client limit set low for the test (global limit high).
- **Steps:** `pytest backend/tests/test_rate_limit.py::test_face_login_throttle_blocks_per_client`
- **Expected:** Requests over the per-client limit are rejected with HTTP `429`.
- **Actual:** Allowed up to the limit, then `HTTPException` status `429`.
- **Status:** **PASS**
- **Note:** Default per-client limit `LALIGENCE_FACE_LOGIN_MAX_PER_MINUTE = 12`. Behind a trusted proxy (`LALIGENCE_TRUST_PROXY_HEADERS=true`, set on the HF build) the client IP is taken from `CF-Connecting-IP` / `X-Forwarded-For` so per-client limiting works behind shared proxy IPs.

### A13 — Face-login global cap (harvesting backstop)
- **Objective:** Total face-login attempts are bounded even when client IPs are shared/spoofed (the hard backstop).
- **Precondition:** Global limit set low for the test; requests come from different client IPs.
- **Steps:** `pytest backend/tests/test_rate_limit.py::test_face_login_throttle_global_cap`
- **Expected:** Once the global cap is reached, further attempts are rejected with HTTP `429` regardless of source IP.
- **Actual:** Two allowed (cap=2 in test), third from a new IP → `HTTPException` status `429`.
- **Status:** **PASS**
- **Note:** Default global cap `LALIGENCE_FACE_LOGIN_GLOBAL_MAX_PER_MINUTE = 60`. Also covered: limiter enforcement and proxy-aware client-IP extraction (`test_rate_limit.py`, 6 tests). Full suite: **83/83 pass**.

### A14 — Gesture step ordering enforced server-side
- **Objective:** A hand-gesture challenge cannot be completed before the server-verified active-liveness step has passed (no skipping ahead via the API).
- **Steps:** `pytest backend/tests/test_gesture_challenge.py::test_gesture_requires_active_liveness_first` — `POST /challenge` for a hand gesture while `active_liveness_passed = false`.
- **Expected:** HTTP `409`.
- **Actual:** HTTP `409` "Complete active liveness before the hand-gesture step."
- **Status:** **PASS**

### A15 — Gesture completion requires a valid one-time nonce
- **Objective:** The gesture step cannot be marked passed by a blind `passed: true` — it needs the server-issued, session-bound nonce.
- **Steps:** `pytest backend/tests/test_gesture_challenge.py::test_gesture_requires_valid_nonce` — complete with (a) no nonce and (b) a wrong nonce.
- **Expected:** HTTP `401` in both cases.
- **Actual:** HTTP `401` "Invalid, missing, or already-used challenge nonce."
- **Status:** **PASS**

### A16 — Gesture nonce is single-use (replay blocked)
- **Objective:** A captured gesture-completion request cannot be replayed (freshness).
- **Steps:** `pytest backend/tests/test_gesture_challenge.py::test_gesture_completes_with_nonce_then_blocks_replay` — complete with the correct nonce, then resubmit the same nonce.
- **Expected:** First → HTTP `200` (challenge passed); replay → HTTP `401` (nonce consumed).
- **Actual:** First `200` + challenge `passed: true`; replay `401`.
- **Status:** **PASS**
- **Note:** Gesture *classification* remains client-side (MediaPipe); full server-side gesture verification needs a backend hand model (future work). Full suite: **86/86 pass**.

---

## Results summary

| ID | Test | Expected | Status |
| --- | --- | --- | --- |
| A1 | Disabled when no token | 403 | **PASS** |
| A2 | Missing token header | 401 | **PASS** |
| A3 | Wrong token | 401 | **PASS** |
| A4 | Correct token | 200 | **PASS** |
| A5 | Delete endpoints guarded | 403 / 401 / 200 | **PASS** |
| A6 | Automated tests | all pass | **PASS** (75/75) |
| A7 | Real PII purged | count 0, no re-seed | **PASS** |
| A8 | HF demo locked | 403 | **PASS** |
| A9 | Verification flow intact | 200 | **PASS** |
| A10 | Document number masked | `PA•••••43` | **PASS** |
| A11 | Face-login redacts PII | sensitive fields dropped | **PASS** |
| A12 | Face-login per-client throttle | 429 over limit | **PASS** |
| A13 | Face-login global cap | 429 over cap | **PASS** |
| A14 | Gesture ordering enforced | 409 | **PASS** |
| A15 | Gesture requires valid nonce | 401 | **PASS** |
| A16 | Gesture nonce single-use (replay) | 200 then 401 | **PASS** |

**Outcome:** 16/16 PASS.

## Residual risks (open — to state honestly in the presentation)

These are **not yet fixed** and remain on the production roadmap (`SECURITY.md`):

- **`POST /api/face-login` is still unauthenticated.** Mitigated (A10–A11): it now returns a redacted profile (masked document number, no full name/DOB/expiry). Adding real authentication remains on the roadmap.
- **Biometric templates and PII are stored unencrypted** (SQLite/PostgreSQL).
- **No API authentication** on the verification endpoints themselves.
- **Hand-gesture step:** mitigated (A14–A16: one-time session-bound nonce + ordering enforcement; replay blocked). Gesture *classification* still runs client-side — full server-side gesture verification (a backend hand model) is future work.
- **Rate limiting is in-memory / single-instance.** Mitigated for face-login (A12–A13: per-client + global throttle, proxy-aware client IP). Production still needs a distributed limiter (Redis) + escalating lockout for multi-instance deployments.

## Reproduction commands (appendix)

```bash
# A6 — automated tests
cd backend && PYTHONPATH="$PWD" ../.venv/bin/python -m pytest tests/test_admin_endpoints.py -v

# A1 — disabled (no token)
curl -s <BASE>/api/profiles -w "\n-> %{http_code}\n"

# A2/A3/A4 — token configured (start with LALIGENCE_ADMIN_API_TOKEN=demo-secret-123)
curl -s <BASE>/api/profiles -w "\n-> %{http_code}\n"                                  # 401
curl -s <BASE>/api/profiles -H "X-Admin-Token: wrong" -w "\n-> %{http_code}\n"        # 401
curl -s <BASE>/api/profiles -H "X-Admin-Token: demo-secret-123" -w "\n-> %{http_code}\n"  # 200

# A9 — verification flow
curl -s -X POST <BASE>/api/verifications -H "Content-Type: application/json" \
  -d '{"user_id":"sec-check"}' -w "\n-> %{http_code}\n"
```
