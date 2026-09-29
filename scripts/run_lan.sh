#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8443}"
HOST="${HOST:-0.0.0.0}"
CERT_DIR="$ROOT/.local-certs"
CERT_FILE="$CERT_DIR/ekyc-local.pem"
KEY_FILE="$CERT_DIR/ekyc-local-key.pem"

detect_ip() {
  local ip=""
  for interface in en0 en1; do
    ip="$(ipconfig getifaddr "$interface" 2>/dev/null || true)"
    if [[ -n "$ip" ]]; then
      printf '%s' "$ip"
      return 0
    fi
  done
  ip="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}' | xargs -I{} ipconfig getifaddr {} 2>/dev/null || true)"
  [[ -n "$ip" ]] && printf '%s' "$ip"
}

LAN_IP="${LAN_IP:-$(detect_ip)}"
if [[ -z "$LAN_IP" ]]; then
  echo "Could not detect a LAN IP. Connect to Wi-Fi or set LAN_IP manually."
  echo "Example: LAN_IP=192.168.1.20 npm run lan"
  exit 1
fi

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  PID="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN | head -1)"
  echo "Port $PORT is already in use by PID $PID."
  echo "Stop it with: kill $PID"
  exit 1
fi

mkdir -p "$CERT_DIR"
NEEDS_CERT=0
if [[ ! -f "$CERT_FILE" || ! -f "$KEY_FILE" ]]; then
  NEEDS_CERT=1
elif ! openssl x509 -in "$CERT_FILE" -noout -ext subjectAltName 2>/dev/null | grep -Fq "IP Address:$LAN_IP"; then
  NEEDS_CERT=1
fi

if [[ "$NEEDS_CERT" == "1" ]]; then
  if ! command -v mkcert >/dev/null 2>&1; then
    echo "mkcert is required to create the local HTTPS certificate."
    echo "Install it with: brew install mkcert"
    exit 1
  fi
  echo "Creating an HTTPS certificate for $LAN_IP..."
  mkcert -install
  mkcert -cert-file "$CERT_FILE" -key-file "$KEY_FILE" localhost 127.0.0.1 "$LAN_IP"
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Python environment not found at .venv/bin/python."
  echo "Create/install the backend environment before running this script."
  exit 1
fi

echo "Building the web frontend..."
npm --prefix frontend run build

export PYTHONPATH="$ROOT/backend"
export LALIGENCE_FRONTEND_DIST="$ROOT/frontend/dist"
export LALIGENCE_DEMO_WALLET="${LALIGENCE_DEMO_WALLET:-1}"
export LALIGENCE_DEMO_WALLET_INITIAL_CENTS="${LALIGENCE_DEMO_WALLET_INITIAL_CENTS:-100000}"
export LALIGENCE_DEMO_WALLET_CURRENCY="${LALIGENCE_DEMO_WALLET_CURRENCY:-USD}"
export LALIGENCE_CORS_ORIGINS="${LALIGENCE_CORS_ORIGINS:-https://localhost:$PORT,https://127.0.0.1:$PORT,https://$LAN_IP:$PORT}"

echo
echo "Kyron frontend + backend"
echo "  This Mac:   https://localhost:$PORT"
echo "  LAN device: https://$LAN_IP:$PORT"
echo "  API docs:   https://$LAN_IP:$PORT/docs"
echo "  Health:     https://$LAN_IP:$PORT/health"
echo
echo "Keep this terminal open. Press Ctrl+C to stop."

exec "$ROOT/.venv/bin/python" -m uvicorn app.main:app \
  --app-dir "$ROOT/backend" \
  --host "$HOST" \
  --port "$PORT" \
  --ssl-certfile "$CERT_FILE" \
  --ssl-keyfile "$KEY_FILE"
