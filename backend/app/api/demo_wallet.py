"""Demo e-wallet API for the KyronPay example app (see services/demo_wallet.py).

Mounted only when LALIGENCE_DEMO_WALLET=1. Endpoints are deliberately simple:
a real deployment would bind every call to the authenticated principal from a
face-login session token instead of trusting user_id in the request body.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.demo_wallet import DemoWalletError, DemoWalletStore
from app.services.profile_store import profile_store

settings = get_settings()
router = APIRouter(prefix="/demo-wallet", tags=["demo-wallet"])
wallet_store = DemoWalletStore(settings.demo_wallet_path or None)


class Transaction(BaseModel):
    kind: str
    amount_cents: int
    counterparty: str
    note: str | None = None
    at: str


class Wallet(BaseModel):
    user_id: str
    display_name: str
    balance_cents: int
    currency: str
    created_at: str
    transactions: list[Transaction] = Field(default_factory=list)


class WalletHolder(BaseModel):
    user_id: str
    display_name: str


class WalletHolderList(BaseModel):
    holders: list[WalletHolder] = Field(default_factory=list)


class ClaimRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)


class TransferRequest(BaseModel):
    from_user_id: str = Field(min_length=1, max_length=120)
    to_user_id: str = Field(min_length=1, max_length=120)
    amount_cents: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=200)


def _wallet_response(payload: dict) -> Wallet:
    return Wallet(currency=settings.demo_wallet_currency, **payload)


@router.post("/claim", response_model=Wallet)
def claim_wallet(request: ClaimRequest) -> Wallet:
    """Create (or return) the wallet for an eKYC-enrolled user.

    The user must already hold an enrolled Face ID -- the wallet is the reward
    for completing verification, mirroring how a fintech would gate account
    opening on KYC.
    """
    profile = next((p for p in profile_store.list_profiles() if p.user_id == request.user_id), None)
    if profile is None:
        raise HTTPException(status_code=404, detail="No enrolled Face ID for this user. Complete eKYC registration first.")
    wallet = wallet_store.create(
        request.user_id,
        profile.full_name or request.user_id,
        settings.demo_wallet_initial_cents,
    )
    return _wallet_response(wallet)


@router.get("/holders", response_model=WalletHolderList)
def list_holders() -> WalletHolderList:
    return WalletHolderList(holders=[WalletHolder(**holder) for holder in wallet_store.list_holders()])


@router.get("/{user_id}", response_model=Wallet)
def get_wallet(user_id: str) -> Wallet:
    try:
        return _wallet_response(wallet_store.get(user_id))
    except DemoWalletError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/transfer", response_model=Wallet)
def transfer(request: TransferRequest) -> Wallet:
    try:
        sender = wallet_store.transfer(request.from_user_id, request.to_user_id, request.amount_cents, request.note)
    except DemoWalletError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _wallet_response(sender)
