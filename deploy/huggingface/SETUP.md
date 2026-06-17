# Deploy Kyron eKYC to a free Hugging Face Space

This gives a permanent, always-on public HTTPS link (e.g.
`https://<your-user>-kyron-ekyc.hf.space`) that anyone can test. The free CPU
tier has enough RAM for the models. The Space repo only needs two files —
`Dockerfile` and `README.md` (in this folder) — because the Dockerfile pulls the
app source from GitHub at build time.

## 1. Create the Space

1. Sign in at https://huggingface.co (free account).
2. Go to **New → Space**.
3. Name it `kyron-ekyc`.
4. **SDK: Docker** → template **Blank**.
5. Hardware: **CPU basic (free)**.
6. Visibility: **Public**.
7. Create the Space.

## 2. Add the two files

Clone the Space repo and copy in this folder's `Dockerfile` and `README.md`:

```bash
git clone https://huggingface.co/spaces/<your-user>/kyron-ekyc
cd kyron-ekyc
cp /path/to/ekyc-system-codex/deploy/huggingface/Dockerfile .
cp /path/to/ekyc-system-codex/deploy/huggingface/README.md .
git add Dockerfile README.md
git commit -m "Kyron eKYC docker space"
git push
```

(You can also use the Space's web UI: **Files → Add file → Upload** both files.)

## 3. Wait for the build

The Space rebuilds automatically on push. The first build is slow (installs
Python deps, downloads face models, builds the frontend) — watch the **Logs**
tab. When it says running, open the Space URL and run a verification.

## Updating

The Dockerfile pins the app to GitHub `main` (`ARG REF=main`). To pull new code,
trigger a rebuild: **Settings → Factory rebuild**, or push any commit to the
Space repo. To pin a specific version, edit `ARG REF` to a tag/commit.

## Customization

- **Build from a fork/branch:** edit `ARG REPO` / `ARG REF` in the `Dockerfile`.
- **CORS:** not needed — the frontend is served from the same origin as `/api`.
- **Persistence:** the free tier is ephemeral (profiles reset on rebuild/sleep).
  Add Space **persistent storage** (paid) and point `DATABASE_URL` at it if you
  need profiles to survive restarts.

## Caveats (free tier)

- Spaces **sleep after inactivity**; the next visit triggers a cold start
  (model warm-up makes the first request slow).
- All visitors share the Space's egress IP, so the backend rate limit
  (240 req/min) is shared — fine for small demos.
- Not your branded domain. For `ekyc.myawswebsite.site` use the AWS/DigitalOcean
  path in `deploy/digitalocean/`.
