# Security Test Runbook

A hands-on, copy-paste guide to re-run and verify every security test case
(A1–A16). Pairs with `docs/security-test-cases.md` (the formal cases + results)
and `SECURITY.md` (posture + roadmap).

Two kinds of test:
- **Automated (pytest)** — deterministic; the authoritative proof for cases that
  need an enrolled match or a full multi-step flow.
- **Live (curl)** — checks the externally-observable behaviour on a running
  instance.

## Part 0 — Setup (once per shell)

```bash
cd /Users/chilanhouthnitvongkhay/Downloads/ekyc-system-codex
# Pick a public base URL to test against (current tunnel or the HF Space):
BASE="https://banku1212-kyron-ekyc.hf.space"
# or your local tunnel URL, e.g. BASE="https://<name>.trycloudflare.com"
```

## Part 1 — Run ALL automated tests (covers A6, A10–A16 logic)

```bash
cd backend
PYTHONPATH="$PWD" ../.venv/bin/python -m pytest tests/ -v
```

**Expected:** `86 passed`. Proves the logic of the admin guard, face-login
redaction + document masking, the rate-limit throttle, and the gesture
nonce / ordering / replay.

Run a single group:

```bash
PYTHONPATH="$PWD" ../.venv/bin/python -m pytest tests/test_admin_endpoints.py -v       # A6
PYTHONPATH="$PWD" ../.venv/bin/python -m pytest tests/test_face_login_redaction.py -v  # A10-A11
PYTHONPATH="$PWD" ../.venv/bin/python -m pytest tests/test_rate_limit.py -v             # A12-A13
PYTHONPATH="$PWD" ../.venv/bin/python -m pytest tests/test_gesture_challenge.py -v      # A14-A16
```

## Part 2 — Live checks (curl)

### A1 / A8 — Admin endpoint locked (no token)

```bash
curl -s "$BASE/api/profiles" -w "\n-> HTTP %{http_code}\n"
```

**Expected:** `HTTP 403` + `"Admin endpoints are disabled..."`
(A1 = tunnel, A8 = HF — run against both).

### A9 — Verification flow still works

```bash
curl -s -X POST "$BASE/api/verifications" -H "Content-Type: application/json" \
  -d '{"user_id":"sec-check"}' -w "\n-> HTTP %{http_code}\n"
```

**Expected:** `HTTP 200` + a session JSON.

### A14 (live) — Gesture nonces are issued

```bash
curl -s -X POST "$BASE/api/verifications" -H "Content-Type: application/json" \
  -d '{"user_id":"nonce-demo"}' \
  | python3 -c "import sys,json; h=json.load(sys.stdin)['hand_challenges']; print('nonce present:', bool(h[0].get('nonce')))"
```

**Expected:** `nonce present: True`.

## Part 3 — Admin token enabled (A2–A5) — local instance with a token

The public instances have admin **disabled** (no token), so test the token path
on a local instance that has one:

```bash
cd /Users/chilanhouthnitvongkhay/Downloads/ekyc-system-codex
LALIGENCE_ADMIN_API_TOKEN="demo-secret-123" PYTHONPATH="$PWD/backend" \
  .venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8099 &
sleep 6
L="http://127.0.0.1:8099"
```

```bash
curl -s "$L/api/profiles" -w "\n-> %{http_code}\n"                                  # A2 no header  -> 401
curl -s "$L/api/profiles" -H "X-Admin-Token: wrong" -w "\n-> %{http_code}\n"        # A3 wrong      -> 401
curl -s "$L/api/profiles" -H "X-Admin-Token: demo-secret-123" -w "\n-> %{http_code}\n"  # A4 correct -> 200
curl -s -X DELETE "$L/api/profiles" -w "\n-> %{http_code}\n"                         # A5 delete no header -> 401
curl -s -X DELETE "$L/api/profiles" -H "X-Admin-Token: demo-secret-123" -w "\n-> %{http_code}\n"  # A5 -> 200
```

**Expected:** `401, 401, 200, 401, 200`. Stop the instance when done:

```bash
lsof -ti:8099 | xargs kill
```

## Part 4 — PII purge proof (A7)

```bash
cd /Users/chilanhouthnitvongkhay/Downloads/ekyc-system-codex
sqlite3 backend/data/laligence_profiles.sqlite3 "SELECT count(*) FROM face_profiles;"
ls backend/data/face_profiles.json 2>/dev/null || echo "legacy seed gone (good)"
```

**Expected:** `0` rows, and the legacy `face_profiles.json` no longer exists.

## Pass / fail sheet

| Case | How | Expected | Result |
| --- | --- | --- | --- |
| A1 / A8 | curl `$BASE/api/profiles` | 403 | |
| A2 | local, no header | 401 | |
| A3 | local, wrong token | 401 | |
| A4 | local, correct token | 200 | |
| A5 | local DELETE | 401 / 200 | |
| A6 | `pytest test_admin_endpoints.py` | pass | |
| A7 | sqlite count + no JSON | 0 / gone | |
| A9 | curl create session | 200 | |
| A10–A11 | `pytest test_face_login_redaction.py` | pass | |
| A12–A13 | `pytest test_rate_limit.py` | pass | |
| A14 | curl session → nonce present | True | |
| A14–A16 | `pytest test_gesture_challenge.py` | pass | |

## Why some cases are pytest-only

Redaction (A10–A11), throttle (A12–A13), and gesture nonce/replay (A14–A16)
need an **enrolled match** or a **full multi-step flow** to trigger live. The
pytest cases drive those deterministically and are the authoritative proof. The
live curl checks cover the externally-observable behaviour (admin lock, flow
intact, nonces issued).
