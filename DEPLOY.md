# Deployment — clarity.rtfmtom.com

Production deploy of the Driftless Clarity Dashboard to a single VPS with
Cloudflare DNS + proxy in front.

**For the Claude Code session running this deploy:** read this document
end-to-end before starting. Ask the operator any questions this doc
doesn't answer. Proceed step by step, pausing for confirmation at the
Cloudflare DNS step (that's the only action they need to do outside the
shell).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Cloudflare                                │
│  DNS: clarity.rtfmtom.com  →  <VPS public IPv4>                  │
│  Proxy: orange-cloud (TLS edge, caching, DDoS)                   │
└──────────────────────────────────────────────────────────────────┘
                              │  HTTPS
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                         Capsul VPS                               │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Caddy (host native, systemd)                              │  │
│  │  • Port 80/443 → automatic Let's Encrypt                   │  │
│  │  • clarity.rtfmtom.com/api/*  → 127.0.0.1:8000             │  │
│  │  • clarity.rtfmtom.com/health → 127.0.0.1:8000             │  │
│  │  • clarity.rtfmtom.com/*      → 127.0.0.1:3000             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                   │
│  ┌───────────────────────────┴────────────────────────────────┐  │
│  │  Docker Compose                                            │  │
│  │  • db   (postgis/postgis:16-3.4, pgdata volume)            │  │
│  │  • api  (FastAPI + APScheduler, 127.0.0.1:8000)            │  │
│  │  • web  (Next.js production build, 127.0.0.1:3000)         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ufw: only 22, 80, 443 exposed. Container ports stay local.     │
└──────────────────────────────────────────────────────────────────┘
```

**Why this shape:** reuses the existing `docker-compose.yml` near-verbatim.
Caddy lives outside Docker so container rebuilds don't take the site
down. Container ports bind to `127.0.0.1` only — no direct internet
exposure. Cloudflare handles edge TLS + DDoS + caching.

---

## 1. Prerequisites on the VPS

SSH in as root (or a sudoer). Run:

```bash
# Base packages
apt update && apt upgrade -y
apt install -y ca-certificates curl gnupg git ufw

# Firewall: lock down to SSH + HTTP(S) only
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Docker (official repo, current version)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Caddy (official repo)
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy

# Confirm
docker --version
docker compose version
caddy version
```

> **If the VPS runs Ubuntu instead of Debian:** change `debian` to `ubuntu`
> in both Docker repo URLs above. Everything else is identical.

---

## 2. Clone the repo and configure `.env`

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/rtfmtom/driftless-turbidity.git
cd driftless-turbidity
git checkout claude/build-from-readme-Xgnl1

# Generate a strong DB password
PG_PASS=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
echo "$PG_PASS"   # copy this — you'll paste into .env

cp .env.example .env
```

Edit `/opt/driftless-turbidity/.env` so it reads:

```ini
POSTGRES_USER=driftless
POSTGRES_PASSWORD=<paste the generated password>
POSTGRES_DB=driftless
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg://driftless:<paste the generated password>@db:5432/driftless
API_PORT=8000
WEB_PORT=3000
NEXT_PUBLIC_API_URL=https://clarity.rtfmtom.com
INGEST_ENABLED=true
INGEST_INTERVAL_MINUTES=15
DRIFTLESS_DEV=0
DRIFTLESS_CORS_ORIGINS=https://clarity.rtfmtom.com
MRMS_ENABLED=true
```

`chmod 600 .env` so only root reads it.

---

## 3. Code edits needed before first prod boot

Three small changes the repo doesn't have yet. The Claude Code session
should apply these as part of the deploy.

### 3a. CORS: read origins from env

`api/src/driftless/config.py` currently hardcodes
`cors_origins=["http://localhost:3000"]`. Change it to read a comma-
separated env var, defaulting to localhost for dev:

```python
# Replace the cors_origins line in class Settings with:
cors_origins: list[str] = ["http://localhost:3000"]

@field_validator("cors_origins", mode="before")
@classmethod
def _split_cors(cls, v):
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return v
```

Make sure `from pydantic import field_validator` is imported. Then
in `.env` the `DRIFTLESS_CORS_ORIGINS` value becomes the prod origin.

> If pydantic-settings already splits comma-separated env values in
> this version, the validator is a no-op — keep it anyway for
> forward compat.

### 3b. Next.js production build in the web container

`web/Dockerfile` currently runs `npm run dev`. Replace with a
multi-stage build that produces a production Next.js server:

```dockerfile
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["npm", "run", "start"]
```

Also update `web/package.json` `"start"` script if needed:
`"start": "next start -p 3000 -H 0.0.0.0"`. (It's already that.)

### 3c. Bind container ports to localhost only

Create `/opt/driftless-turbidity/docker-compose.prod.yml`:

```yaml
services:
  db:
    # Postgres doesn't need any host port mapping in prod; it's only
    # reached from the api container over the internal network.
    ports: []

  api:
    ports:
      - "127.0.0.1:${API_PORT:-8000}:8000"
    environment:
      DRIFTLESS_DEV: "0"
      DRIFTLESS_CORS_ORIGINS: ${DRIFTLESS_CORS_ORIGINS}

  web:
    ports:
      - "127.0.0.1:${WEB_PORT:-3000}:3000"
    environment:
      NODE_ENV: production
      NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL}
    # No bind mounts in prod — use the built image.
    volumes: []
    command: ["npm", "run", "start"]
```

This overrides the dev `docker-compose.yml` so that (a) ports only
bind to loopback, (b) the `web` container runs the prod build instead
of dev mode, (c) the `db` container isn't exposed to the host at all.

---

## 4. Caddy configuration

Replace `/etc/caddy/Caddyfile` with:

```
clarity.rtfmtom.com {
    encode gzip zstd

    # Health and all API paths → FastAPI
    @api path /api/* /health
    reverse_proxy @api 127.0.0.1:8000

    # Everything else → Next.js
    reverse_proxy 127.0.0.1:3000

    log {
        output file /var/log/caddy/clarity.log {
            roll_size 10MiB
            roll_keep 5
        }
    }
}
```

Then:

```bash
mkdir -p /var/log/caddy
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

**Important:** Caddy will try to fetch a Let's Encrypt certificate as
soon as it starts handling the domain. That only succeeds once
Cloudflare DNS resolves `clarity.rtfmtom.com` to this VPS. Do the next
step first.

---

## 5. Cloudflare DNS

Operator action — in the Cloudflare dashboard for `rtfmtom.com`:

1. DNS → Records → Add record:
   - Type: **A**
   - Name: `clarity`
   - IPv4 address: **<VPS public IPv4>** (from `curl -4 ifconfig.me` on the VPS)
   - Proxy status: **Proxied** (orange cloud)
   - TTL: Auto

2. SSL/TLS → Overview → encryption mode: **Full (strict)**.
   (Caddy gets a real Let's Encrypt cert, so Full Strict is correct.)

3. SSL/TLS → Edge Certificates → "Always Use HTTPS" = **On**.

4. Wait ~30s, then from the VPS: `dig +short clarity.rtfmtom.com` —
   should resolve to a Cloudflare IP (not your VPS IP — the orange
   cloud proxies).

> If you see "Too many certificates already issued" from Let's Encrypt,
> wait a week or switch Caddy to use Cloudflare's DNS-01 challenge
> (requires an API token). Unlikely on a first deploy.

---

## 6. First boot

```bash
cd /opt/driftless-turbidity

# Build and start in production mode
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Watch API come up (ctrl-C when you see "Application startup complete")
docker compose logs -f api
```

The API entrypoint runs `alembic upgrade head` on boot, so migrations
0001 through 0005 apply automatically, including the seed gauges
(migration 0002) and the replacement Kickapoo stations (migration 0003).
The scheduler kicks a USGS ingest ~5s after boot and will run projections
20s after that.

**Then run the one-time population jobs in order.** These are not
scheduled; they only need to happen once per freshly-provisioned DB:

```bash
# 1. Basin polygons from NLDI (3 network calls, ~30s)
docker compose exec api python -m driftless.basins.delineate --all-watched -v

# 2. Basin characteristics: NLCD + SSURGO + slope (slow, ~3-5 min total)
docker compose exec api python -m driftless.basins.characterize --all -v

# 3. 90-day MRMS rainfall backfill (slow, ~30-60 min on f1-m @ concurrency=2)
#    NOTE: concurrency=4 recommended if this is an f1-l or larger.
docker compose exec api python -m driftless.ingest.mrms \
  --backfill-hours 2160 --concurrency 2 -v

# 4. First projection (also runs hourly on its own after this)
docker compose exec api python -m driftless.projection.heuristic --all-watched -v
```

---

## 7. Verification

```bash
# From the VPS:
curl -sS http://127.0.0.1:8000/health
# → {"status":"ok","db":"ok","scheduler":"running"}

# From the outside world, after Cloudflare proxies:
curl -sS https://clarity.rtfmtom.com/health
curl -sS https://clarity.rtfmtom.com/api/streams | jq 'length'   # → 3

# Browser:
#   https://clarity.rtfmtom.com        → map + watch list
#   https://clarity.rtfmtom.com/streams/<id>   → detail page with charts
```

If the browser loads but the map/data is empty, check
`docker compose logs api | grep -iE 'ingest|projection|error'`.

---

## 8. Ongoing operations

**Tailing logs:**
```bash
docker compose logs -f api         # USGS + MRMS + projections
docker compose logs -f web         # Next.js requests
tail -f /var/log/caddy/clarity.log # HTTP access log
```

**Updating to a newer branch commit:**
```bash
cd /opt/driftless-turbidity
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# Migrations apply on api startup.
```

**Disk monitoring:** Docker image layers + Postgres can accumulate.
Occasionally:
```bash
df -h                                        # check disk usage
docker system prune -af                      # remove unused images/containers
# (Don't add --volumes unless you want to wipe the DB!)
```

**Restart everything cleanly:**
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart
```

**Back up the DB (pg_dump to the VPS, then rsync off-box):**
```bash
docker compose exec -T db pg_dump -U driftless driftless \
  | gzip > /root/driftless-$(date +%Y%m%d).sql.gz
```

---

## 9. What isn't automated yet (future work)

- Daily DB backup to off-box storage (S3/B2/rsync).
- TLS renewal is automatic via Caddy, but monitor `caddy.service` status.
- Phase 4 will add observation logging, which needs no deploy changes.
- Phase 5 notifications would need SMTP/Pushover creds added to `.env`.

---

## Quick-reference: file changes this deploy requires

| File | Change |
|---|---|
| `api/src/driftless/config.py` | Read `DRIFTLESS_CORS_ORIGINS` as comma-separated list |
| `web/Dockerfile` | Multi-stage prod build (`npm run build` + `npm start`) |
| `docker-compose.prod.yml` | New file — overrides port bindings + prod commands |
| `/etc/caddy/Caddyfile` | New — reverse proxy config |
| `/opt/driftless-turbidity/.env` | New — from `.env.example` with prod values |

None of the application code logic changes.
