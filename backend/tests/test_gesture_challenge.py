from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app

client = TestClient(app)


def _session(active_liveness_passed: bool = True):
    created = client.post("/api/verifications", json={"user_id": "gesture-test"}).json()
    sid = created["session_id"]
    headers = {"X-Session-Token": created["session_token"]}
    session = routes.store.get(UUID(sid))
    session.biometric.active_liveness_passed = active_liveness_passed
    return sid, session, headers


def test_gesture_requires_active_liveness_first() -> None:
    sid, session, headers = _session(active_liveness_passed=False)
    ch = session.hand_challenges[0]
    r = client.post(
        f"/api/verifications/{sid}/challenge",
        json={"challenge_id": ch.id, "passed": True, "nonce": ch.nonce},
        headers=headers,
    )
    assert r.status_code == 409


def test_gesture_requires_valid_nonce() -> None:
    sid, session, headers = _session()
    ch = session.hand_challenges[0]
    # missing nonce
    assert client.post(
        f"/api/verifications/{sid}/challenge",
        json={"challenge_id": ch.id, "passed": True},
        headers=headers,
    ).status_code == 401
    # wrong nonce
    assert client.post(
        f"/api/verifications/{sid}/challenge",
        json={"challenge_id": ch.id, "passed": True, "nonce": "not-the-nonce"},
        headers=headers,
    ).status_code == 401


def test_gesture_completes_with_nonce_then_blocks_replay() -> None:
    sid, session, headers = _session()
    ch = session.hand_challenges[0]
    nonce = ch.nonce

    ok = client.post(
        f"/api/verifications/{sid}/challenge",
        json={"challenge_id": ch.id, "passed": True, "nonce": nonce},
        headers=headers,
    )
    assert ok.status_code == 200
    assert any(c["id"] == ch.id and c["passed"] for c in ok.json()["hand_challenges"])

    # Replaying the same (now consumed) nonce must fail.
    replay = client.post(
        f"/api/verifications/{sid}/challenge",
        json={"challenge_id": ch.id, "passed": True, "nonce": nonce},
        headers=headers,
    )
    assert replay.status_code == 401
