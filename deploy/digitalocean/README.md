# Branded Single-Domain Deployment (DigitalOcean + Route 53)

This deploys the **whole Kyron eKYC app** behind one branded HTTPS domain
(`ekyc.myawswebsite.site`) on a single server with Docker Compose:

- `caddy`: serves the built Vite frontend **and** reverse-proxies `/api/*` to the
  backend. Automatic HTTPS via Let's Encrypt. (Built from `Dockerfile.web`.)
- `api`: FastAPI backend built from the project root `Dockerfile`.
- `postgres`: PostgreSQL for verified profiles and enrolled Face ID templates.

Because the frontend and API share one origin, there is **no Vercel step and no
cross-origin CORS** to manage. Testers just open `https://ekyc.myawswebsite.site`.

## Why this shape

The camera (getUserMedia) only works over HTTPS, so the public demo must be
served over TLS. Serving frontend + API from the same domain keeps it simple and
fast, and avoids the dev-server slowness you get when tunnelling Vite. A server
near Southeast Asia (Singapore) gives Laos testers low latency and stays up
without depending on your Mac.

## Requirements

- A server (DigitalOcean Droplet in Singapore recommended), Ubuntu 22.04/24.04 LTS.
- **At least 2 vCPU / 4 GB RAM** — the backend loads OCR, OpenCV, ONNX, and
  anti-spoofing models.
- Access to the `myawswebsite.site` hosted zone in **AWS Route 53** (this domain's
  DNS is on AWS, not Cloudflare).

## 1. Create the server

In DigitalOcean: create a Droplet, Region **Singapore**, Ubuntu LTS,
**2 vCPU / 4 GB RAM** or larger, add your SSH key, create. Note its public IP.

## 2. Point the branded domain at it (Route 53)

In the AWS Route 53 console, open the `myawswebsite.site` hosted zone and create:

```text
Record name:  ekyc.myawswebsite.site
Type:         A
Value:        <droplet-public-ip>
TTL:          300
```

(Or with the AWS CLI — replace ZONE_ID and the IP:)

```bash
aws route53 change-resource-record-sets --hosted-zone-id ZONE_ID --change-batch '{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "ekyc.myawswebsite.site",
      "Type": "A",
      "TTL": 300,
      "ResourceRecords": [{ "Value": "<droplet-public-ip>" }]
    }
  }]
}'
```

Wait until it resolves:

```bash
dig +short ekyc.myawswebsite.site
```

## 3. Bootstrap the server

```bash
ssh root@<droplet-public-ip>
curl -fsSL https://raw.githubusercontent.com/Blank-develop/ekyc-system-codex/main/deploy/digitalocean/bootstrap-ubuntu.sh -o bootstrap-ubuntu.sh
bash bootstrap-ubuntu.sh
exit && ssh root@<droplet-public-ip>   # re-login so the docker group applies
```

## 4. Clone and configure

```bash
git clone https://github.com/Blank-develop/ekyc-system-codex.git
cd ekyc-system-codex
cp deploy/digitalocean/.env.example deploy/digitalocean/.env
nano deploy/digitalocean/.env
```

Set:

```bash
SITE_DOMAIN=ekyc.myawswebsite.site
LALIGENCE_CORS_ORIGINS=https://ekyc.myawswebsite.site
POSTGRES_PASSWORD=$(openssl rand -base64 36)   # paste the generated value
```

## 5. Build and start

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml up -d --build
```

The first build is slow (installs Python deps, downloads face models, builds the
frontend). Watch progress:

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml logs -f api caddy
```

## 6. Verify

```bash
# Frontend (expect HTTP/2 200):
curl -I https://ekyc.myawswebsite.site/

# Backend via the proxied /api path (expect 200 + a JSON session):
curl -s -X POST https://ekyc.myawswebsite.site/api/verifications \
  -H "Content-Type: application/json" -d '{"user_id":"healthcheck"}' -w "\nHTTP %{http_code}\n"
```

(The backend's own `/health` is only reachable inside the container — Caddy
exposes just `/api/*` — so use an `/api` call to verify it end-to-end.)

Then open **https://ekyc.myawswebsite.site** in a browser and run a verification.
The camera should prompt for permission (HTTPS origin).

## 7. Update the deployment

```bash
cd ekyc-system-codex && git pull
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml up -d --build
```

## 8. Back up PostgreSQL

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml exec postgres \
  pg_dump -U laligence -d laligence_ekyc > laligence_ekyc_backup.sql
```

## Troubleshooting

### Caddy does not get HTTPS
- `dig +short ekyc.myawswebsite.site` must return the droplet IP.
- Ports `80` and `443` open (the bootstrap script opens them).
- `SITE_DOMAIN` in `.env` is the hostname only — no `https://`.
- `docker compose ... logs -f caddy`

### App loads but API calls fail
- Confirm the `api` container is healthy: `docker compose ... ps`.
- `/api/*` is proxied by Caddy to `api:8000`; check Caddy + api logs.

### First request is slow
- The backend warms face/anti-spoof models on first use. Keep the container
  running; 4 GB RAM gives smoother loading.

### Uploads fail with 413
Raise `LALIGENCE_MAX_UPLOAD_SIZE_BYTES` in `.env`, then
`docker compose ... up -d`.

## Production notes

Appropriate for company testing/demos. Before production: authenticated API
access, protect/remove the profile admin endpoints, encrypt biometric templates
at rest, audit logs + retention/deletion, monitoring, automated PostgreSQL
backups, and consider DigitalOcean Managed PostgreSQL.
