"""Watchlist (biographic) screening: matching precision and hit lifecycle."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.config import get_settings
from app.services.watchlist_store import WatchlistStore, normalize_name, normalize_passport


@pytest.fixture()
def store(tmp_path):
    url = f"sqlite:///{tmp_path / 'wl.db'}"
    s = WatchlistStore(url)
    s.import_subjects(
        [
            {
                "full_name": "MURRAY ROSS SMITH",
                "date_of_birth": "1962-12-14",
                "nationality": "AUS",
                "passport_numbers": ["PB5870043"],
                "reason": "Interpol Red Notice (test)",
                "source_ref": "RN-1",
            },
            {
                "full_name": "JOHN DOE",
                "date_of_birth": "1990-01-01",
                "nationality": "USA",
                "passport_numbers": ["X1234567", "Y7654321"],
                "reason": "National watchlist (test)",
            },
        ],
        source="test-list",
        replace=True,
    )
    settings = get_settings()
    settings.watchlist_enabled = True
    yield s
    settings.watchlist_enabled = False


def test_normalizers():
    assert normalize_passport(" pb 5870-043 ") == "PB5870043"
    # name order does not matter (MRZ surname-first vs printed given-first)
    assert normalize_name("SMITH MURRAY ROSS") == normalize_name("Murray Ross Smith")


def test_passport_exact_match(store):
    matches = store.screen(passport_number="pb 5870043", full_name=None, date_of_birth=None)
    assert len(matches) == 1
    assert matches[0].matched_on == "passport_number"
    assert matches[0].confidence >= 0.95


def test_name_plus_dob_match_is_order_independent(store):
    matches = store.screen(
        passport_number=None, full_name="SMITH MURRAY ROSS", date_of_birth=date(1962, 12, 14)
    )
    assert matches and matches[0].matched_on == "name_dob"


def test_name_with_wrong_dob_does_not_match(store):
    # Same-ish name but a different DOB and not near-exact spelling: no hit.
    matches = store.screen(
        passport_number=None, full_name="MURRAY SMITH", date_of_birth=date(2000, 1, 1)
    )
    assert matches == []


def test_clean_traveller_has_no_hit(store):
    matches = store.screen(
        passport_number="ZZ9999999", full_name="ALICE EXAMPLE", date_of_birth=date(1995, 5, 5)
    )
    assert matches == []


def test_disabled_returns_no_matches(store):
    get_settings().watchlist_enabled = False
    matches = store.screen(passport_number="PB5870043", full_name=None, date_of_birth=None)
    assert matches == []


def test_hit_lifecycle_and_summary(store):
    match = store.screen(passport_number="PB5870043", full_name=None, date_of_birth=None)[0]
    hit_id = store.record_hit("sess-1", "user-1", match)
    pending = store.list_hits(status="pending")
    assert len(pending) == 1 and pending[0]["subject_name"] == "MURRAY ROSS SMITH"
    assert store.adjudicate_hit(hit_id, "confirmed", actor="officer-a", note="stopped at booth")
    assert store.list_hits(status="pending") == []
    confirmed = store.list_hits(status="confirmed")
    assert confirmed[0]["adjudicated_by"] == "officer-a"
    summary = store.summary()
    assert summary["total_hits"] == 1 and summary["pending_hits"] == 0
