# swiftdeploy

A declarative container deployment CLI. Write `manifest.yaml` once — swiftdeploy generates all configs, manages the container lifecycle, and keeps your stack running.

```
manifest.yaml  ──►  swiftdeploy init  ──►  nginx.conf
                                      ──►  docker-compose.yml
                                      ──►  docker compose up
```

## Architecture

```
                ┌────────────────────────────────────┐
                │           manifest.yaml            │
                │       (single source of truth)     │
                └────────────┬───────────────────────┘
                             │
                    swiftdeploy init
                             │
              ┌──────────────▼──────────────┐
              │                             │
         nginx.conf              docker-compose.yml
              │                             │
              └──────────────┬──────────────┘
                             │
                    docker compose up
                             │
              ┌──────────────┴──────────────┐
              │                             │
    ┌─────────▼─────────┐       ┌───────────▼──────────┐
    │   nginx:latest    │       │  swift-deploy-1-node  │
    │   port 8080       │──────►│  port 3000 (internal) │
    │   reverse proxy   │       │  stable / canary mode │
    └───────────────────┘       └──────────────────────-┘
```

## Prerequisites

- Docker ≥ 24 with Compose v2
- Python 3.8+ with PyYAML (`pip install pyyaml`)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/yourname/swiftdeploy
cd swiftdeploy

# 2. Build the API image
docker build -t swift-deploy-1-node:latest .

# 3. Deploy
./swiftdeploy deploy

# 4. Test
curl http://localhost:8080/
curl http://localhost:8080/healthz
```

## Subcommands

### `init`
Parses `manifest.yaml` and generates `nginx.conf` and `docker-compose.yml` from templates.

```bash
./swiftdeploy init
```

All generated files are derived from `manifest.yaml` — never edit them by hand.

---

### `validate`
Runs 5 pre-flight checks and exits non-zero on any failure.

```bash
./swiftdeploy validate
```

Checks:
1. `manifest.yaml` exists and is valid YAML
2. All required fields are present and non-empty
3. The Docker image referenced in the manifest exists locally
4. The Nginx port is not already bound on the host
5. The generated `nginx.conf` is syntactically valid (via `nginx -t`)

---

### `deploy`
Runs `init`, brings up the stack, and blocks until health checks pass (60s timeout).

```bash
./swiftdeploy deploy
```

---

### `promote`
Switches deployment mode with a rolling service restart (app container only).

```bash
./swiftdeploy promote canary   # switch to canary mode
./swiftdeploy promote stable   # revert to stable mode
```

What it does:
1. Updates `mode` field in `manifest.yaml` in-place
2. Regenerates `docker-compose.yml` with the new `MODE` env var
3. Restarts the app container only (`--no-deps --force-recreate`)
4. Confirms the new mode by hitting `/healthz`

---

### `teardown`
Removes all containers, networks, and volumes.

```bash
./swiftdeploy teardown           # stop and remove containers
./swiftdeploy teardown --clean   # also delete generated configs
```

---

## API Endpoints

| Method | Path      | Description |
|--------|-----------|-------------|
| GET    | `/`       | Welcome message with mode, version, timestamp |
| GET    | `/healthz`| Liveness check with status and uptime |
| POST   | `/chaos`  | Simulate degraded behaviour *(canary only)* |

### Chaos Modes (canary only)

```bash
# Slow down responses
curl -X POST http://localhost:8080/chaos \
  -H 'Content-Type: application/json' \
  -d '{"mode": "slow", "duration": 3}'

# Random 500 errors at 50% rate
curl -X POST http://localhost:8080/chaos \
  -H 'Content-Type: application/json' \
  -d '{"mode": "error", "rate": 0.5}'

# Recover — cancel all chaos
curl -X POST http://localhost:8080/chaos \
  -H 'Content-Type: application/json' \
  -d '{"mode": "recover"}'
```

---

## manifest.yaml Reference

```yaml
services:
  image: swift-deploy-1-node:latest   # Docker image (required)
  port: 3000                          # App port (required)
  mode: stable                        # stable | canary
  version: "1.0.0"                    # Injected as APP_VERSION
  restart_policy: unless-stopped      # Docker restart policy
  log_volume: swiftdeploy-logs        # Named volume for logs

nginx:
  image: nginx:latest                 # Nginx image (required)
  port: 8080                         # Host port (required)
  proxy_timeout: 30                   # Upstream timeout (seconds)
  contact: ops@swiftdeploy.io         # Shown in error JSON bodies

network:
  name: swiftdeploy-net               # Docker network name (required)
  driver_type: bridge                 # Network driver (required)
```

---

## Nginx Access Log Format

```
$time_iso8601 | $status | ${request_time}s | $upstream_addr | $request
```

Example:
```
2024-01-15T12:34:56+00:00 | 200 | 0.002s | 172.18.0.3:3000 | GET / HTTP/1.1
```

---

## Security

- Containers run as a **non-root user** (`appuser`)
- Linux capabilities dropped (`cap_drop: ALL`) with only necessary ones added
- Service port is **never exposed directly** — all traffic routes through Nginx
- `no-new-privileges` security option applied

---

## Project Structure

```
swiftdeploy/
├── manifest.yaml          # ← single source of truth (edit this)
├── swiftdeploy            # ← CLI executable
├── Dockerfile             # ← API service image
├── app/
│   └── main.py            # ← API service (Python)
├── templates/
│   ├── nginx.conf.j2      # ← Nginx config template
│   └── docker-compose.yml.j2  # ← Compose template
├── nginx.conf             # ← generated by init (do not edit)
├── docker-compose.yml     # ← generated by init (do not edit)
└── README.md
```