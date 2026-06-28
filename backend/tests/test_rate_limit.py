from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import routes
from app.services.rate_limit import SlidingWindowLimiter


class _Client:
    def __init__(self, host: str) -> None:
        self.host = host


class _Req:
    def __init__(self, headers: dict[str, str], host: str) -> None:
        self.headers = headers
        self.client = _Client(host)


def test_limiter_blocks_after_max() -> None:
    limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert limiter.allow("a") is False  # 4th over the limit
    assert limiter.allow("b") is True   # a different key is independent


def test_limiter_disabled_when_zero() -> None:
    limiter = SlidingWindowLimiter(max_events=0)
    assert all(limiter.allow("x") for _ in range(100))


def test_client_ip_uses_proxy_header_when_trusted(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "trust_proxy_headers", True)
    req = _Req({"x-forwarded-for": "1.2.3.4, 10.0.0.1"}, "10.0.0.1")
    assert routes._client_ip(req) == "1.2.3.4"
    req_cf = _Req({"cf-connecting-ip": "5.6.7.8", "x-forwarded-for": "1.2.3.4"}, "10.0.0.1")
    assert routes._client_ip(req_cf) == "5.6.7.8"


def test_client_ip_ignores_proxy_header_when_untrusted(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "trust_proxy_headers", False)
    req = _Req({"x-forwarded-for": "1.2.3.4"}, "10.0.0.1")
    assert routes._client_ip(req) == "10.0.0.1"


def test_face_login_throttle_blocks_per_client(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "trust_proxy_headers", False)
    monkeypatch.setattr(routes, "_face_login_global_limiter", SlidingWindowLimiter(1000))
    monkeypatch.setattr(routes, "_face_login_client_limiter", SlidingWindowLimiter(2))
    req = _Req({}, "9.9.9.9")
    routes.face_login_rate_limit(req)  # 1
    routes.face_login_rate_limit(req)  # 2
    with pytest.raises(HTTPException) as exc:
        routes.face_login_rate_limit(req)  # 3 -> blocked
    assert exc.value.status_code == 429


def test_face_login_throttle_global_cap(monkeypatch) -> None:
    monkeypatch.setattr(routes.settings, "trust_proxy_headers", False)
    monkeypatch.setattr(routes, "_face_login_global_limiter", SlidingWindowLimiter(2))
    monkeypatch.setattr(routes, "_face_login_client_limiter", SlidingWindowLimiter(1000))
    # Different client IPs each time, but the global cap still trips.
    routes.face_login_rate_limit(_Req({}, "1.1.1.1"))
    routes.face_login_rate_limit(_Req({}, "2.2.2.2"))
    with pytest.raises(HTTPException) as exc:
        routes.face_login_rate_limit(_Req({}, "3.3.3.3"))
    assert exc.value.status_code == 429
