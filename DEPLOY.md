# Deploying myt convert

A Linux server running Docker. Images are built by GitHub Actions and pulled
from GHCR, so the server never compiles anything — the worker image carries
PaddlePaddle and LibreOffice and would take a long time to build in place.

## What you need

| | Minimum | Comfortable |
| --- | --- | --- |
| vCPU | 2 | 4 |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 40 GB |

The worker image is about 3 GB and OCR is CPU-bound: expect roughly 10 s per
scanned page on 4 modern vCPUs, several times that on 2. Digital PDFs — anything
exported from Word, Excel or an accounting system — convert in well under a
second and barely touch the CPU. Disk is mostly the images; job artefacts are
small, but they accumulate.

## 1. Install Docker

On a fresh Ubuntu 22.04 or 24.04 box:

```bash
curl -fsSL https://get.docker.com | sh
```

Then allow your user to run it without `sudo` (log out and back in afterwards):

```bash
sudo usermod -aG docker $USER
```

## 2. Get the deployment files

Only two files are needed on the server, but cloning keeps updates simple:

```bash
git clone https://github.com/kavishjoaheer18/myt-convert.git && cd myt-convert
```

## 3. Configure

```bash
cp .env.prod.example .env
```

Edit `.env` and set at minimum a database password. Generate one with:

```bash
openssl rand -base64 32
```

Add `ANTHROPIC_API_KEY` if you want the consensus pass — without it conversions
still work, they just get no second opinion and nothing is routed for review.

## 4. Start it

```bash
docker compose -f docker-compose.prod.yml up -d
```

First start pulls about 4 GB. Check it came up:

```bash
docker compose -f docker-compose.prod.yml ps
```

The app is on port 3000. Confirm the API answers through the frontend's proxy:

```bash
curl -s localhost:3000/api/health
```

That should print `{"status":"ok","service":"myt convert"}`.

## 5. Put TLS in front of it

Nothing in the stack terminates TLS, and port 3000 should not face the internet
directly. Two options.

### Cloudflare tunnel — no open ports, no certificates

Matches the pattern already used for ClinicFlow. Create a named tunnel in Zero
Trust, point the public hostname at `http://frontend:3000`, then:

```bash
docker run -d --name myt-cloudflared --restart unless-stopped --network myt-convert_default cloudflare/cloudflared:latest tunnel --no-autoupdate run --token YOUR_TUNNEL_TOKEN
```

The server needs no inbound firewall rule at all.

### Caddy — if the server has a public IP and a domain

Point an A record at the server, then create `/etc/caddy/Caddyfile`:

```
convert.example.com {
    reverse_proxy localhost:3000
}
```

Caddy obtains and renews the certificate itself.

## 6. Upgrading

Every push to `main` publishes new images. To take them:

```bash
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
```

To pin a known-good build instead of following `main`, set `IMAGE_TAG` in `.env`
to a `sha-` tag from the GHCR package page and re-run the same command.

For automatic updates, add Watchtower as on the NAS — though on a converter that
people are actively using, a deliberate pull is usually the better trade.

## Backups

Two volumes hold everything that matters:

- `myt-convert_postgres-data` — jobs, cells, discrepancies, corrections
- `myt-convert_job-data` — uploaded PDFs and produced workbooks

```bash
docker run --rm -v myt-convert_postgres-data:/data -v $PWD:/backup alpine tar czf /backup/postgres-$(date +%F).tar.gz -C /data .
```

The `paddle-models` volume is a cache — it re-downloads if lost, so it does not
need backing up.

## Operating notes

- **Logs:** `docker compose -f docker-compose.prod.yml logs -f worker`. Every
  line is JSON and carries the `job_id`, so a single conversion can be followed
  end to end.
- **First scanned PDF is slow.** The OCR models download on first use (~200 MB)
  into the `paddle-models` volume. Later conversions skip that.
- **Restarting mid-conversion** loses that job: the task is acknowledged late,
  so Redis will redeliver it, but the job row may sit in `PROCESSING`. Re-upload
  is the simplest fix.
- **No authentication.** The brief scoped this to single-user, so anyone who can
  reach the URL can convert and download. Put it behind Cloudflare Access, a VPN,
  or your reverse proxy's basic auth before exposing it to anyone else.
