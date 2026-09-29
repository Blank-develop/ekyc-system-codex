#!/usr/bin/env bash
#
# start_kyron.sh — launch the Kyron eKYC combined server (frontend + API) over
# HTTPS on the local network. Self-healing: auto-detects the current LAN IP,
# regenerates the TLS cert when the IP changes, and reads durable admin secrets
# from .local-certs/ (so a /tmp wipe never disables auth again).
#
# Run it yourself:   ./start_kyron.sh
# Change the port:   KYRON_PORT=8090 ./start_kyron.sh
#
set -euo pipefail
cd "$(dirname "$0")"                 # repo root (this script lives there)

PORT="${KYRON_PORT:-8443}"
CERT_DIR=".local-certs"
KEY="$CERT_DIR/ekyc-local-key.pem"
CRT="$CERT_DIR/ekyc-local.pem"
PY=".venv/bin/python"
mkdir -p "$CERT_DIR"

# 1) Durable admin secrets — generated once, survive /tmp cleanups.
[ -s "$CERT_DIR/jwt_secret.txt" ] || "$PY" -c "import secrets;print(secrets.token_urlsafe(48))" > "$CERT_DIR/jwt_secret.txt"
[ -s "$CERT_DIR/encryption_key.txt" ] || "$PY" -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())" > "$CERT_DIR/encryption_key.txt"
[ -s "$CERT_DIR/auth_users.txt" ] || "$PY" scripts/hash_password.py admin admin "Kyron#Admin2026" > "$CERT_DIR/auth_users.txt"

# 2) Detect the current LAN IP (Wi-Fi first, then Ethernet).
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 127.0.0.1)"

# 3) (Re)generate the self-signed cert whenever it does not cover this IP.
if ! openssl x509 -in "$CRT" -noout -text 2>/dev/null | grep -q "IP Address:$IP"; then
  echo "Issuing TLS cert for $IP ..."
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$KEY" -out "$CRT" -days 825 \
    -subj "/CN=ekyc-local" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:$IP" 2>/dev/null
fi

# 4) Free the port if a stale instance is holding it.
lsof -tnP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1 | xargs -I{} kill {} 2>/dev/null || true

# 5) Environment.
export LALIGENCE_JWT_SECRET="$(cat "$CERT_DIR/jwt_secret.txt")"
export LALIGENCE_AUTH_USERS="$(cat "$CERT_DIR/auth_users.txt")"
export LALIGENCE_FRONTEND_DIST="$PWD/frontend/dist"
export DATABASE_URL="sqlite:////$PWD/backend/ekyc_local.db"
# Border/immigration pilot: retain the evidence behind every crossing.
# Remove these three lines to restore the default no-raw-image-retention posture.
# Encrypts biometric templates AND retained evidence frames at rest.
export LALIGENCE_ENCRYPTION_KEY="$(cat "$CERT_DIR/encryption_key.txt")"
export LALIGENCE_EVIDENCE_ENABLED="${LALIGENCE_EVIDENCE_ENABLED:-true}"
export LALIGENCE_EVIDENCE_ROOT="$PWD/evidence"
export LALIGENCE_EVIDENCE_RETENTION_DAYS="${LALIGENCE_EVIDENCE_RETENTION_DAYS:-1825}"
export LALIGENCE_CORS_ORIGINS="https://$IP:$PORT,https://localhost:$PORT"
# Watchlist ("blacklist") biographic screening. Import a list first, e.g.:
#   PYTHONPATH=backend .venv/bin/python scripts/import_watchlist.py <list.csv> --replace
# Watchlist screening is enabled for this deployment. An explicit environment
# value can still override it for maintenance or isolated tests.
export LALIGENCE_WATCHLIST_ENABLED="${LALIGENCE_WATCHLIST_ENABLED:-true}"

echo "Kyron eKYC  ->  https://$IP:$PORT"
echo "Admin       ->  https://$IP:$PORT/#admin   (admin / Kyron#Admin2026)"
exec "$PY" -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "$PORT" \
  --ssl-keyfile "$KEY" --ssl-certfile "$CRT"
