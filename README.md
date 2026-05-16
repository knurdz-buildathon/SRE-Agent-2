# SRE Agent — Docker Monitoring Console

A Docker-based monitoring agent that discovers Docker Compose websites, continuously checks their health and performance, detects issues, creates incidents, explains likely root causes, and shows suggested fixes in a dark-themed web dashboard.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  sre-agent-web  │────▶│  sre-agent-api   │────▶│  SQLite DB  │
│  React + Tailwind│     │  FastAPI + Workers│     │  (volume)   │
│  :3111           │     │  :8000           │     │             │
└─────────────────┘     └────────┬─────────┘     └─────────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              Docker Socket  Traefik Logs  Playwright
                    │            │            │
              ┌─────┴────┐ ┌────┴─────┐ ┌────┴──────┐
              │ Container │ │ Access   │ │ Browser   │
              │ Metrics   │ │ Log      │ │ Checks    │
              │ Discovery │ │ Parser   │ │           │
              └──────────┘ └──────────┘ └───────────┘
```

## Quick Start

```bash
# Clone and enter the project
cd sre-agent

# Copy environment config
cp .env.example .env

# Start everything
docker compose up --build -d

# Open the dashboard
open http://localhost:3111
```

The dashboard opens at **http://localhost:3111**. The API is at **http://localhost:8777**.

## Demo Mode

When `DEMO_MODE=true` (default), the agent seeds sample data including:

- A **healthy** sample app that responds 200 on `/health` with `#app` selector
- A **crashing** sample app that exits with code 1, creating a crash-loop incident
- A **staging API** service with TCP dependency checks
- Historical health check data for uptime charts
- Sample Traefik 404/5xx user-facing errors

## Monitoring Your Own Services

Add these Docker labels to any container in your `docker-compose.yml`:

```yaml
services:
  my-web-app:
    image: my-app:latest
    labels:
      sre.monitor: "true"
      sre.slug: "my-web-app"
      sre.environment: "production"
      sre.git_url: "https://github.com/org/my-app"
      sre.health_url: "http://my-web-app:3000/health"
      sre.browser_url: "http://my-web-app:3000"
      sre.expected_selector: "#root"
      sre.tcp_checks: "db:5432,redis:6379,minio:9000"
```

### Label Reference

| Label | Required | Description |
|-------|----------|-------------|
| `sre.monitor` | Yes | Must be `"true"` for the agent to discover this container |
| `sre.slug` | Yes | Unique name for the deployment |
| `sre.environment` | No | Environment tag (default: `production`) |
| `sre.git_url` | No | Git repository URL |
| `sre.health_url` | No | HTTP health check URL |
| `sre.browser_url` | No | URL for Playwright browser checks |
| `sre.expected_selector` | No | CSS selector expected on the page |
| `sre.tcp_checks` | No | Comma-separated `host:port` pairs for TCP checks |

## What Gets Monitored

### HTTP Health Checks (every 30s)
- Status code, response time, timeout detection, error messages
- Incidents created for failures, 5xx, timeouts

### TCP Dependency Checks
- Validates backing services (databases, caches) are reachable
- Incidents for connection failures

### Browser Checks (Playwright)
- Detects blank pages, missing expected selectors, JS crashes
- Incidents for render failures and missing elements

### Docker Container Metrics
- Container state, restart count, exit codes
- CPU %, memory usage, network RX/TX
- High CPU/memory alerts

### Traefik Access Log Analysis
- Parses JSON and common log formats
- Detects repeated 4xx (user errors) and 5xx (server errors)
- Groups by path, method, status code
- Auto-creates incidents for repeated errors

### Infrastructure
- OS, kernel, Docker version
- CPU count, total memory, disk usage
- Docker image/volume/build-cache sizes
- Disk pressure alerts

## Incident Detection & Deduplication

Incidents are **deduplicated** by deployment + category + fingerprint. If an issue continues, timeline events are appended instead of creating duplicates. When health recovers, incidents are automatically resolved.

### Incident Categories & Suggested Fixes

| Category | Severity | Example Fix |
|----------|----------|-------------|
| Container not running | Critical | Check docker compose logs, required env vars, and build output |
| Container restarting | Critical | Check logs for crash reason, verify env vars, check OOM kills |
| HTTP health failure | Critical | Check service port, health endpoint, firewall |
| HTTP timeout | Critical | Check CPU/memory, network, upstream deps |
| HTTP 5xx | Critical | Check application logs for stack traces |
| Browser render failure | Critical | Check frontend build and web server |
| Missing selector | Degraded | Check frontend JS crash or build artifact path |
| Repeated 4xx from Traefik | Warning | Check router rule, fallback route, missing assets |
| High CPU | Warning | Consider CPU limits, check runaway processes |
| High memory | Warning | Consider memory limits, check for leaks |
| TCP dependency failure | Critical | Check backing service is running and reachable |
| Disk pressure | Warning | Prune Docker resources or expand disk |
| Likely env/config issue | Critical | Check .env file, secrets, config mounts |

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/overview` | Total deployments, healthy/unhealthy counts, open incidents |
| GET | `/api/deployments/{id}/health?limit=50` | Health check history |
| GET | `/api/deployments/{id}/errors` | Failed health checks |
| GET | `/api/deployments/{id}/stats?hours=24` | Resource usage metrics |
| GET | `/api/deployments/{id}/uptime?days=30` | Uptime history by day |
| GET | `/api/deployments/{id}/env-issues` | Environment/config incidents |
| GET | `/api/deployments/{id}/user-errors` | User-facing errors for this deployment |
| GET | `/api/incidents` | All incidents (filter by status/severity) |
| GET | `/api/incidents/{id}` | Incident detail with timeline |
| GET | `/api/errors` | All failed health checks |
| GET | `/api/user-errors` | User-facing errors from Traefik logs |
| GET | `/api/user-errors/summary` | Aggregated error summary |
| GET | `/api/infrastructure` | VPS metadata, Docker sizes, container list |

## Dashboard Pages

1. **Overview** — Total deployments, healthy/unhealthy counts, open incidents, deployment cards with status and uptime
2. **Deployment Detail** — Health checks, errors, resource charts (CPU/memory), uptime bar chart, env issues, user errors
3. **Incidents** — Filterable incident list with severity badges, suggested fixes, click for timeline detail
4. **Infrastructure** — VPS info, Docker disk usage, CPU/memory bars per deployment, container list
5. **User Errors** — Top failing paths, error category breakdown, status code distribution, hit counts

## Traefik Log Integration

Mount your Traefik access log directory into the API container:

```yaml
services:
  sre-agent-api:
    volumes:
      - /path/to/traefik/logs:/traefik-logs:ro
    environment:
      - TRAEFIK_LOG_DIR=/traefik-logs
```

Both JSON and Common Log Format are supported.

## Security Notes

- Logs are treated as **untrusted data** — no commands from logs are ever executed
- The Docker socket is **not exposed** through public APIs
- Dashboard auth: set `DASHBOARD_USER` and `DASHBOARD_PASS` env vars, or protect with VPN/reverse proxy auth
- Environment variable values are redacted in log display
- API runs as read-only on the Docker socket (`:ro`)

## Running Tests

Use a virtualenv so dependency versions match `requirements.txt` (avoids FastAPI/Pydantic mismatches with a global Python install).

```bash
cd api
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=.   # Windows PowerShell: $env:PYTHONPATH="."
pytest app/tests -v
```

API tests use `TEST_MODE`/`DATABASE_PATH` set inside `test_api.py`; collector/parser tests need no DB.

## Project Structure

```
sre-agent/
├── docker-compose.yml
├── .env.example
├── traefik-logs/
│   └── access.log          # Sample Traefik log
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   └── app/
│       ├── main.py         # FastAPI app + startup
│       ├── models/
│       │   ├── database.py # SQLite schema + helpers
│       │   └── schemas.py  # Pydantic models
│       ├── collectors/
│       │   ├── docker_collector.py
│       │   ├── health_collector.py
│       │   ├── browser_collector.py
│       │   └── traefik_parser.py
│       ├── engines/
│       │   └── incident_detector.py
│       ├── workers/
│       │   ├── monitor.py  # Scheduler + check runners
│       │   └── demo.py     # Demo/seed data
│       ├── routers/
│       │   ├── overview.py
│       │   ├── deployments.py
│       │   ├── incidents.py
│       │   ├── errors.py
│       │   └── infrastructure.py
│       └── tests/
│           ├── test_traefik_parser.py
│           ├── test_incident_detector.py
│           ├── test_health_collector.py
│           └── test_api.py
├── web/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── nginx.conf
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── api.js
│       ├── index.css
│       ├── components/
│       │   ├── StatusBadge.jsx
│       │   ├── SeverityBadge.jsx
│       │   ├── MetricCard.jsx
│       │   ├── DeploymentCard.jsx
│       │   ├── UptimeChart.jsx
│       │   └── ResourceChart.jsx
│       └── pages/
│           ├── OverviewPage.jsx
│           ├── DeploymentPage.jsx
│           ├── IncidentsPage.jsx
│           ├── IncidentDetailPage.jsx
│           ├── InfrastructurePage.jsx
│           └── UserErrorsPage.jsx
├── sample-healthy/
│   ├── Dockerfile
│   └── app.py
└── sample-crash/
    ├── Dockerfile
    └── crash.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_PATH` | `/data/sre.db` | SQLite database path |
| `TRAEFIK_LOG_DIR` | `/traefik-logs` | Traefik access log directory |
| `DOCKER_SOCKET` | `/var/run/docker.sock` | Docker socket path |
| `CHECK_INTERVAL` | `30` | Check interval in seconds |
| `DASHBOARD_USER` | `admin` | Basic auth username |
| `DASHBOARD_PASS` | `admin` | Basic auth password |
| `DEMO_MODE` | `true` | Seed demo data when no labels found |
| `AUTH_ENABLED` | `true` | Enable basic auth |
