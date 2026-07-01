from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import numpy as np

from app.core.config import get_settings
from app.services import template_protection as tp
from app.services.template_protection import TemplateProtector


def _unit(seed: int, dim: int = 128) -> list[float]:
    v = np.random.default_rng(seed).standard_normal(dim)
    return (v / np.linalg.norm(v)).tolist()


def _dot(a, b) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


# --- Core math: orthonormal transform preserves the matching score exactly -----

def test_protect_preserves_dot_product_and_norm() -> None:
    prot = TemplateProtector("rotate-key-1")
    a, b = _unit(1), _unit(2)
    pa, pb = prot.protect(a), prot.protect(b)

    assert abs(_dot(pa, pb) - _dot(a, b)) < 1e-9  # score preserved
    assert abs(_dot(pa, pa) - 1.0) < 1e-9         # norm preserved (still unit)
    assert pa != a                                 # but the stored form changed


def test_protect_is_noop_without_key() -> None:
    prot = TemplateProtector("")
    assert not prot.enabled
    a = _unit(3)
    assert prot.protect(a) == a


def test_protect_is_deterministic() -> None:
    a = _unit(4)
    assert TemplateProtector("k").protect(a) == TemplateProtector("k").protect(a)


def test_different_keys_are_unlinkable() -> None:
    # Same person's template under two different keys must not be comparable
    # (cross-key dot != raw dot), which is the ISO 24745 unlinkability property.
    a, b = _unit(5), _unit(6)
    k1, k2 = TemplateProtector("key-A"), TemplateProtector("key-B")
    assert abs(_dot(k1.protect(a), k2.protect(b)) - _dot(a, b)) > 1e-3


# --- End-to-end through the profile store -------------------------------------

def _enroll(store, user_id: str, template: list[float]) -> None:
    from app.models.schemas import VerificationResult

    now = datetime.now(timezone.utc)
    result = VerificationResult(session_id=uuid4(), user_id=user_id, created_at=now, updated_at=now)
    store.enroll(result, template)


def test_match_score_unchanged_by_protection(tmp_path, monkeypatch) -> None:
    from app.services.profile_store import FaceProfileStore

    compare = lambda a, b: (sum(x * y for x, y in zip(a, b)) + 1) / 2  # noqa: E731
    enrolled = _unit(10)
    probe = _unit(11)

    def score_with_key(key: str, db: str) -> float:
        monkeypatch.setattr(get_settings(), "template_protection_key", key)
        tp.get_template_protector.cache_clear()
        store = FaceProfileStore(database_url=f"sqlite:///{tmp_path}/{db}")
        _enroll(store, "u1", enrolled)
        return store.match(probe, compare, 0.0).score

    plain = score_with_key("", "plain.sqlite3")
    protected = score_with_key("rotate-1", "prot.sqlite3")
    tp.get_template_protector.cache_clear()

    assert plain == protected  # accuracy is preserved exactly


def test_protected_store_does_not_hold_raw_template(tmp_path, monkeypatch) -> None:
    from app.services.profile_store import FaceProfileStore

    monkeypatch.setattr(get_settings(), "template_protection_key", "rotate-1")
    tp.get_template_protector.cache_clear()
    try:
        raw = _unit(12)
        store = FaceProfileStore(database_url=f"sqlite:///{tmp_path}/p.sqlite3")
        _enroll(store, "u1", raw)
        stored = store._active_records()[0]["face_template"]
        assert stored != raw                         # raw biometric not stored
        assert abs(_dot(stored, stored) - 1.0) < 1e-6  # but still a unit template
    finally:
        tp.get_template_protector.cache_clear()
