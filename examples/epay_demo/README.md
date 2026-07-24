# KyronPay — demo e-payment app (Flutter)

A small but realistic e-wallet that shows **how a fintech customer integrates
the Kyron eKYC platform**, end to end:

1. **Register with eKYC** — opens the hosted Kyron flow in the browser
   (passport scan → liveness → Face ID enrollment), like a hosted checkout.
2. **Claim a wallet** — the app calls the demo-wallet API; a verified user
   gets a seeded welcome balance.
3. **Send money** — transfers between verified users.
4. **Login by face** — native camera burst → `EkycClient.faceLoginBurst()`
   (replay-resistant multi-frame login) → straight into the wallet.

## Answer to "Dart package or API?"

Both, layered — and this app demonstrates it:

| Layer | What it is | Who runs it |
|---|---|---|
| **Kyron API** | The product. All biometrics (PAD models, MRZ OCR, face matching) run server-side. | You (Kyron) |
| **`laligence_ekyc` Dart package** (`sdk/flutter`) | Thin typed client the customer's app embeds. | Customer's app |
| **Hosted web flow** | Fastest registration integration (browser/WebView) — no native capture code needed. | You (Kyron), embedded by customer |
| **KyronPay (this app)** | Plays the role of the customer's e-wallet. The wallet ledger is a demo stub for what would be *their* payments backend. | Demo |

## Run it

1. Start the Kyron server with the demo wallet enabled:

   ```bash
   LALIGENCE_DEMO_WALLET=1 ... uvicorn app.main:app --app-dir backend ...
   ```

2. Run the app pointing at the server (defaults to `https://192.168.100.253:8090`):

   ```bash
   cd examples/epay_demo
   flutter run --dart-define=KYRON_BASE_URL=https://<your-lan-ip>:8090
   ```

3. On the phone: register through the hosted flow first (accept the
   self-signed certificate once in the browser), then claim your wallet with
   the same user ID, then try **Login with my face**.

## Demo-only caveats (do not ship)

- The demo trusts the dev server's **self-signed certificate**
  (`AppConfig.trustSelfSignedCertificates`).
- The wallet API is **unauthenticated**; a real integration binds every call
  to the principal from a face-login session token.
- The ledger is a JSON file on the server (`LALIGENCE_DEMO_WALLET_PATH`).
