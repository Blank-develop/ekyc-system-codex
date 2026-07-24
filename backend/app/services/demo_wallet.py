"""Demo e-wallet ledger for the KyronPay example app.

DEMO ONLY -- this module exists so a fintech/e-wallet customer integration can
be exercised end to end (register via eKYC -> seeded balance -> transfers ->
face login) before any real customer front-end is connected. It is mounted
only when LALIGENCE_DEMO_WALLET=1 and must never be enabled in a production
deployment: it has no authentication of its own and its ledger is a local
JSON file, not a real payments backend.

Balances are integer cents to avoid float money bugs. All mutations happen
under one process-wide lock and are snapshotted to disk, so the demo survives
server restarts but intentionally nothing more.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_TRANSACTIONS_KEPT = 50


class DemoWalletError(ValueError):
    """Raised for business-rule violations (insufficient funds, unknown user)."""


class DemoWalletStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._wallets: dict[str, dict] = {}
        self._load()

    # -- queries ---------------------------------------------------------
    def exists(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._wallets

    def get(self, user_id: str) -> dict:
        with self._lock:
            wallet = self._wallets.get(user_id)
            if wallet is None:
                raise DemoWalletError(f"No wallet for user '{user_id}'. Register through eKYC first.")
            return json.loads(json.dumps(wallet))  # deep copy

    def list_holders(self) -> list[dict]:
        with self._lock:
            return [
                {"user_id": user_id, "display_name": wallet["display_name"]}
                for user_id, wallet in sorted(self._wallets.items())
            ]

    # -- mutations -------------------------------------------------------
    def create(self, user_id: str, display_name: str | None, initial_cents: int) -> dict:
        now = self._now()
        with self._lock:
            if user_id in self._wallets:
                return json.loads(json.dumps(self._wallets[user_id]))
            wallet = {
                "user_id": user_id,
                "display_name": display_name or user_id,
                "balance_cents": initial_cents,
                "created_at": now,
                "transactions": [
                    {
                        "kind": "seed",
                        "amount_cents": initial_cents,
                        "counterparty": "kyronpay",
                        "note": "Welcome bonus for completing eKYC verification",
                        "at": now,
                    }
                ],
            }
            self._wallets[user_id] = wallet
            self._save()
            return json.loads(json.dumps(wallet))

    def transfer(self, from_user_id: str, to_user_id: str, amount_cents: int, note: str | None = None) -> dict:
        if amount_cents <= 0:
            raise DemoWalletError("Transfer amount must be positive.")
        if from_user_id == to_user_id:
            raise DemoWalletError("Cannot transfer to yourself.")
        now = self._now()
        with self._lock:
            sender = self._wallets.get(from_user_id)
            recipient = self._wallets.get(to_user_id)
            if sender is None:
                raise DemoWalletError(f"No wallet for sender '{from_user_id}'.")
            if recipient is None:
                raise DemoWalletError(f"No wallet for recipient '{to_user_id}'.")
            if sender["balance_cents"] < amount_cents:
                raise DemoWalletError("Insufficient balance.")
            sender["balance_cents"] -= amount_cents
            recipient["balance_cents"] += amount_cents
            self._append(sender, {"kind": "transfer_out", "amount_cents": -amount_cents, "counterparty": to_user_id, "note": note, "at": now})
            self._append(recipient, {"kind": "transfer_in", "amount_cents": amount_cents, "counterparty": from_user_id, "note": note, "at": now})
            self._save()
            return json.loads(json.dumps(sender))

    def reset(self) -> None:
        with self._lock:
            self._wallets = {}
            self._save()

    # -- internals -------------------------------------------------------
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _append(wallet: dict, transaction: dict) -> None:
        wallet["transactions"].insert(0, transaction)
        del wallet["transactions"][MAX_TRANSACTIONS_KEPT:]

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            self._wallets = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._wallets = {}

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._wallets, indent=1), encoding="utf-8")
        except OSError:
            pass  # demo store: losing persistence is acceptable, crashing is not
