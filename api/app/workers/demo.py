"""Demo/seed mode: generates sample data when no Docker labels are found."""
import logging
import random
from datetime import datetime, timedelta
from app.models.database import execute, fetch_one, fetch_all

logger = logging.getLogger("sre")

DEMO_DEPLOYMENTS = [
    {
        "id": "sample-healthy",
        "slug": "sample-healthy",
        "environment": "production",
        "git_url": "https://github.com/example/healthy-app",
        "health_url": "http://sample-healthy-app:8080/health",
        "browser_url": "http://sample-healthy-app:8080",
        "expected_selector": "#app",
        "tcp_checks": "sample-healthy-app:8080",
        "container_id": "demo-healthy-id",
        "container_name": "sample-healthy-app",
        "image": "sample-healthy:latest",
        "status": "up",
    },
    {
        "id": "sample-crash",
        "slug": "sample-crash",
        "environment": "production",
        "git_url": "https://github.com/example/crash-app",
        "health_url": "http://sample-crash-app:3000/health",
        "browser_url": "http://sample-crash-app:3000",
        "expected_selector": "#root",
        "tcp_checks": "sample-crash-app:3000",
        "container_id": "demo-crash-id",
        "container_name": "sample-crash-app",
        "image": "sample-crash:latest",
        "status": "down",
    },
    {
        "id": "sample-api",
        "slug": "sample-api",
        "environment": "staging",
        "git_url": "https://github.com/example/api-service",
        "health_url": "http://sample-api:4000/health",
        "browser_url": None,
        "expected_selector": None,
        "tcp_checks": "sample-api:4000,db:5432",
        "container_id": "demo-api-id",
        "container_name": "sample-api",
        "image": "api-service:v2.1",
        "status": "up",
    },
]


async def seed_demo_deployments():
    """Seed demo deployments if none exist."""
    existing = await fetch_all("SELECT id FROM deployments")
    existing_ids = {r["id"] for r in existing}

    for dep in DEMO_DEPLOYMENTS:
        if dep["id"] not in existing_ids:
            await execute(
                """INSERT INTO deployments
                    (id, slug, environment, git_url, health_url, browser_url,
                     expected_selector, tcp_checks, probe_host_header, container_id, container_name,
                     image, status, last_check)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    dep["id"], dep["slug"], dep["environment"], dep["git_url"],
                    dep["health_url"], dep["browser_url"], dep["expected_selector"],
                    dep["tcp_checks"], None,
                    dep["container_id"], dep["container_name"],
                    dep["image"], dep["status"], datetime.utcnow().isoformat(),
                ),
            )
    logger.info(f"Demo: seeded {len(DEMO_DEPLOYMENTS)} deployments")


async def run_demo_container_checks():
    """Generate demo container metrics."""
    now = datetime.utcnow().isoformat()

    # Healthy app: low resource usage, running
    await execute(
        """INSERT INTO container_metrics
            (deployment_id, container_state, restart_count, exit_code,
             cpu_percent, memory_usage_mb, memory_limit_mb,
             network_rx_bytes, network_tx_bytes, collected_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("sample-healthy", "running", 0, 0,
         round(random.uniform(1, 15), 2), round(random.uniform(30, 80), 2), 512,
         random.randint(1000, 50000), random.randint(500, 30000), now),
    )

    # Crash app: restarting, high CPU
    await execute(
        """INSERT INTO container_metrics
            (deployment_id, container_state, restart_count, exit_code,
             cpu_percent, memory_usage_mb, memory_limit_mb,
             network_rx_bytes, network_tx_bytes, collected_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("sample-crash", "restarting", random.randint(5, 20), 1,
         round(random.uniform(50, 99), 2), round(random.uniform(100, 450), 2), 512,
         0, 0, now),
    )

    # API: running, moderate resources
    await execute(
        """INSERT INTO container_metrics
            (deployment_id, container_state, restart_count, exit_code,
             cpu_percent, memory_usage_mb, memory_limit_mb,
             network_rx_bytes, network_tx_bytes, collected_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("sample-api", "running", 0, 0,
         round(random.uniform(5, 30), 2), round(random.uniform(50, 120), 2), 256,
         random.randint(5000, 100000), random.randint(2000, 50000), now),
    )

    # Trigger container incidents for crash app
    from app.engines.incident_detector import create_or_update_incident, make_fingerprint
    await create_or_update_incident(
        deployment_id="sample-crash",
        title="Container restarting (exit code 1)",
        severity="critical",
        trigger_type="docker",
        error_category="container_restarting",
        suggested_fix="Container is in a crash loop (restarting). Check `docker compose logs` for the crash reason, verify env vars, and check OOM kills.",
        fingerprint=make_fingerprint("sample-crash", "container_restarting"),
    )


async def run_demo_infra_checks():
    """Generate demo VPS and Docker size data."""
    now = datetime.utcnow().isoformat()

    await execute(
        """INSERT INTO vps_metadata
            (target_id, os_name, kernel, docker_version, cpu_count, memory_total_mb, disk_total_gb, disk_used_gb, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("local", "Linux 5.15.0", "5.15.0-91-generic", "24.0.7", 4, 8192.0, 100.0, 42.5, now),
    )

    await execute(
        """INSERT INTO docker_sizes
            (target_id, images_mb, containers_mb, volumes_mb, build_cache_mb, collected_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        ("local", 2540.5, 320.2, 890.1, 156.3, now),
    )


async def seed_demo_historical_data():
    """Seed historical health check data for charts."""
    existing = await fetch_one(
        "SELECT COUNT(*) as cnt FROM health_checks WHERE deployment_id = ?",
        ("sample-healthy",),
    )
    if existing and existing["cnt"] and existing["cnt"] > 0:
        logger.debug("Demo historical data already present, skipping")
        return

    now = datetime.utcnow()

    # Healthy: mostly successful checks
    for i in range(100):
        ts = (now - timedelta(minutes=i * 5)).isoformat()
        success = 1 if random.random() > 0.05 else 0
        status = 200 if success else 503
        resp_time = round(random.uniform(10, 80) if success else 0, 2)
        error = None if success else "Service Unavailable"
        await execute(
            """INSERT INTO health_checks (deployment_id, check_type, status_code, response_time_ms, success, error_message, checked_at)
            VALUES (?, 'http', ?, ?, ?, ?, ?)""",
            ("sample-healthy", status, resp_time, success, error, ts),
        )

    # Crash: mostly failed checks
    for i in range(100):
        ts = (now - timedelta(minutes=i * 5)).isoformat()
        success = 1 if random.random() > 0.85 else 0
        status = 200 if success else random.choice([500, 502, 503])
        resp_time = round(random.uniform(5, 30) if success else 0, 2)
        error = None if success else random.choice(["Connection refused", "Bad Gateway", "Timeout"])
        await execute(
            """INSERT INTO health_checks (deployment_id, check_type, status_code, response_time_ms, success, error_message, checked_at)
            VALUES (?, 'http', ?, ?, ?, ?, ?)""",
            ("sample-crash", status, resp_time, success, error, ts),
        )

    # API: mostly successful with occasional slowdowns
    for i in range(100):
        ts = (now - timedelta(minutes=i * 5)).isoformat()
        success = 1 if random.random() > 0.1 else 0
        status = 200 if success else 500
        resp_time = round(random.uniform(20, 200) if success else 0, 2)
        error = None if success else "Internal Server Error"
        await execute(
            """INSERT INTO health_checks (deployment_id, check_type, status_code, response_time_ms, success, error_message, checked_at)
            VALUES (?, 'http', ?, ?, ?, ?, ?)""",
            ("sample-api", status, resp_time, success, error, ts),
        )

    # Seed some user errors
    user_errors_data = [
        ("/api/v1/users", "GET", 404, "not_found", 47),
        ("/assets/main.js", "GET", 404, "not_found", 23),
        ("/api/v1/auth/login", "POST", 401, "unauthorized", 15),
        ("/api/v1/data/export", "GET", 500, "internal_error", 8),
        ("/favicon.ico", "GET", 404, "not_found", 12),
    ]
    for path, method, code, cat, count in user_errors_data:
        await execute(
            """INSERT INTO user_errors (deployment_id, path, method, status_code, error_category, count, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (None, path, method, code, cat, count,
             (now - timedelta(hours=24)).isoformat(), now.isoformat()),
        )

    logger.info("Demo historical data seeded")
