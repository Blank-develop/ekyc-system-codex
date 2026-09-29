from __future__ import annotations

import pytest

from app.services.demo_wallet import DemoWalletError, DemoWalletStore


def _store(tmp_path=None) -> DemoWalletStore:
    return DemoWalletStore(tmp_path / "wallets.json" if tmp_path else None)


def test_create_seeds_initial_balance_and_welcome_transaction() -> None:
    store = _store()
    wallet = store.create("alice", "Alice A", 100_000)

    assert wallet["balance_cents"] == 100_000
    assert wallet["display_name"] == "Alice A"
    assert wallet["transactions"][0]["kind"] == "seed"


def test_create_is_idempotent() -> None:
    store = _store()
    store.create("alice", "Alice", 100_000)
    again = store.create("alice", "Alice Again", 999)

    assert again["balance_cents"] == 100_000
    assert again["display_name"] == "Alice"


def test_transfer_moves_funds_and_records_both_sides() -> None:
    store = _store()
    store.create("alice", "Alice", 100_000)
    store.create("bob", "Bob", 100_000)

    sender = store.transfer("alice", "bob", 25_000, note="lunch")

    assert sender["balance_cents"] == 75_000
    assert store.get("bob")["balance_cents"] == 125_000
    assert sender["transactions"][0]["kind"] == "transfer_out"
    assert sender["transactions"][0]["amount_cents"] == -25_000
    assert store.get("bob")["transactions"][0]["kind"] == "transfer_in"
    assert store.get("bob")["transactions"][0]["counterparty"] == "alice"


def test_transfer_rejects_insufficient_funds_self_and_unknown_users() -> None:
    store = _store()
    store.create("alice", "Alice", 1_000)
    store.create("bob", "Bob", 1_000)

    with pytest.raises(DemoWalletError):
        store.transfer("alice", "bob", 2_000)
    with pytest.raises(DemoWalletError):
        store.transfer("alice", "alice", 100)
    with pytest.raises(DemoWalletError):
        store.transfer("ghost", "bob", 100)
    with pytest.raises(DemoWalletError):
        store.transfer("alice", "ghost", 100)
    with pytest.raises(DemoWalletError):
        store.transfer("alice", "bob", 0)
    # balances unchanged after every rejected attempt
    assert store.get("alice")["balance_cents"] == 1_000
    assert store.get("bob")["balance_cents"] == 1_000


def test_persistence_across_store_instances(tmp_path) -> None:
    path = tmp_path / "wallets.json"
    first = DemoWalletStore(path)
    first.create("alice", "Alice", 50_000)

    second = DemoWalletStore(path)
    assert second.get("alice")["balance_cents"] == 50_000
    assert second.list_holders() == [{"user_id": "alice", "display_name": "Alice"}]


def test_get_unknown_wallet_raises() -> None:
    store = _store()
    with pytest.raises(DemoWalletError):
        store.get("nobody")
