# DigitalOcean Singapore Droplet Deployment

This deployment runs the LALIGENCE eKYC API on a DigitalOcean Droplet in Singapore with Docker Compose:

- `api`: FastAPI backend built from the project `Dockerfile`.
- `postgres`: PostgreSQL for verified profiles and enrolled Face ID templates.
- `caddy`: HTTPS reverse proxy with automatic TLS certificates.

The frontend should be deployed separately on Vercel and configured to call the API domain.

## Why This Setup

Render was slow for this project because the backend loads OCR, OpenCV, ONNX, and anti-spoofing models. A Droplet avoids platform sleep and gives the API a stable machine close to Laos and Southeast Asia testers.

## Requirements

- DigitalOcean Droplet in Singapore.
- Ubuntu 24.04 LTS or 22.04 LTS.
- Recommended minimum: 2 vCPU / 4 GB RAM for internal demos.
- A domain or subdomain for the API, for example `api.your-domain.com`.
- DNS A record pointing the API domain to the Droplet public IP.
- Vercel account for the frontend.

You need a real API domain because the Vercel frontend runs on HTTPS. Browsers block HTTPS pages from calling an insecure `http://droplet-ip:8000` backend.

## 1. Create The Droplet

In DigitalOcean:

1. Create Droplet.
2. Region: Singapore.
3. Image: Ubuntu LTS.
4. Size: at least 2 vCPU / 4 GB RAM for smoother AI model loading.
5. Add your SSH key.
6. Create the Droplet.

Point DNS:

```text
api.your-domain.com  A  <droplet-public-ip>
```

Wait until DNS resolves:

```bash
dig +short api.your-domain.com
```

## 2. Bootstrap The Droplet

SSH into the Droplet:

```bash
ssh root@<droplet-public-ip>
```

Install Docker and open ports:

```bash
curl -fsSL https://raw.githubusercontent.com/Blank-develop/ekyc-system-codex/main/deploy/digitalocean/bootstrap-ubuntu.sh -o bootstrap-ubuntu.sh
bash bootstrap-ubuntu.sh
```

Log out and back in so Docker group permissions apply:

```bash
exit
ssh root@<droplet-public-ip>
```

## 3. Clone The Repository

```bash
git clone https://github.com/Blank-develop/ekyc-system-codex.git
cd ekyc-system-codex
```

## 4. Configure Production Env

```bash
cp deploy/digitalocean/.env.example deploy/digitalocean/.env
nano deploy/digitalocean/.env
```

Set:

```bash
API_DOMAIN=api.your-domain.com
LALIGENCE_CORS_ORIGINS=https://your-vercel-project.vercel.app
POSTGRES_PASSWORD=<long-random-password>
```

Generate a password:

```bash
openssl rand -base64 36
```

You can update `LALIGENCE_CORS_ORIGINS` after Vercel gives you the final frontend URL.

## 5. Start The Backend Stack

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml up -d --build
```

Watch logs:

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml logs -f api caddy
```

Check health:

```bash
curl -i https://api.your-domain.com/health
```

Expected:

```text
HTTP/2 200
```

## 6. Deploy Frontend To Vercel

In Vercel:

1. Import `https://github.com/Blank-develop/ekyc-system-codex`.
2. Framework preset: Vite.
3. Root directory: repository root.
4. Build command: `npm install && npm --prefix frontend run build`.
5. Output directory: `frontend/dist`.
6. Add environment variable:

```bash
VITE_API_BASE_URL=https://api.your-domain.com
```

Deploy the project.

After Vercel gives the production URL, update the Droplet env:

```bash
nano deploy/digitalocean/.env
```

Set:

```bash
LALIGENCE_CORS_ORIGINS=https://your-vercel-project.vercel.app
```

Restart the API:

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml up -d
```

If you also use a custom Vercel domain, include both origins separated by commas:

```bash
LALIGENCE_CORS_ORIGINS=https://your-vercel-project.vercel.app,https://ekyc.your-domain.com
```

## 7. Update The Deployment

On the Droplet:

```bash
cd ekyc-system-codex
git pull
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml up -d --build
```

## 8. Backup PostgreSQL

Create a backup:

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml exec postgres \
  pg_dump -U laligence -d laligence_ekyc > laligence_ekyc_backup.sql
```

Restore a backup:

```bash
cat laligence_ekyc_backup.sql | docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml exec -T postgres \
  psql -U laligence -d laligence_ekyc
```

## Troubleshooting

### Vercel Shows Failed To Fetch

Check:

- `VITE_API_BASE_URL` is `https://api.your-domain.com`.
- The API health endpoint works from your laptop.
- `LALIGENCE_CORS_ORIGINS` includes the exact Vercel origin.
- Restart API after changing CORS env.

### Caddy Does Not Get HTTPS

Check:

- DNS A record points to the Droplet IP.
- Ports `80` and `443` are open.
- `API_DOMAIN` in `.env` has no `https://`, only the hostname.
- Caddy logs:

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml logs -f caddy
```

### API Is Slow On First Request

The backend loads face and anti-spoofing models. A Droplet avoids sleep, but the first request after container restart can still warm models. Keep the container running and use at least 4 GB RAM for smoother testing.

### Uploads Fail With 413

Increase:

```bash
LALIGENCE_MAX_UPLOAD_SIZE_BYTES=12582912
```

Then restart:

```bash
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/docker-compose.yml up -d
```

## Production Notes

This setup is appropriate for company testing and demos. Before production:

- Add authenticated API access.
- Protect or remove profile admin endpoints.
- Encrypt biometric templates at rest.
- Add audit logs and retention/deletion workflows.
- Add monitoring and alerts.
- Configure automated PostgreSQL backups.
- Consider DigitalOcean Managed PostgreSQL instead of container PostgreSQL for stronger durability.
