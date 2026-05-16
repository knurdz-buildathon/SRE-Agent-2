import asyncio
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.models.database import execute, fetch_one, fetch_all
from app.collectors.docker_collector import (
    discover_deployments,
    collect_container_metrics,
    collect_vps_metadata,
    collect_docker_sizes,
)
from app.collectors.health_collector import http_health_check, run_tcp_checks
from app.collectors.browser_collector import browser_check
from app.collectors.traefik_parser import (
    collect_traefik_logs,
    categorize_user_errors,
    detect_traefik_incidents,
)
from app.engines.incident_detector import (
    detect_container_incidents,
    detect_health_incidents,
    detect_browser_incidents,
    detect_tcp_incidents,
    detect_disk_pressure,
    create_or_update_incident,
    make_fingerprint,
    resolve_incident,
    SUGGESTED_FIXES,
)

logger = logging.getLogger("sre")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

scheduler = AsyncIOScheduler()


async def purge_deployment_from_db(deployment_id: str):
    """Remove deployment row and dependent metrics (SQLite has no FK CASCADE)."""
    await execute(
        "DELETE FROM incident_timeline WHERE incident_id IN (SELECT id FROM incidents WHERE deployment_id = ?)",
        (deployment_id,),
    )
    await execute("DELETE FROM incidents WHERE deployment_id = ?", (deployment_id,))
    await execute("DELETE FROM health_checks WHERE deployment_id = ?", (deployment_id,))
    await execute("DELETE FROM tcp_checks WHERE deployment_id = ?", (deployment_id,))
    await execute("DELETE FROM browser_checks WHERE deployment_id = ?", (deployment_id,))
    await execute("DELETE FROM container_metrics WHERE deployment_id = ?", (deployment_id,))
    await execute("DELETE FROM traefik_logs WHERE deployment_id = ?", (deployment_id,))
    await execute("DELETE FROM user_errors WHERE deployment_id = ?", (deployment_id,))
    await execute("DELETE FROM deployments WHERE id = ?", (deployment_id,))


async def sync_deployments():
    """Discover Docker deployments and upsert into DB."""
    if DEMO_MODE:
        from app.workers.demo import seed_demo_deployments
        await seed_demo_deployments()
        return

    deployments, docker_ok = discover_deployments()
    if not docker_ok:
        logger.warning("Docker discovery unavailable; keeping existing deployment rows in SQLite")
        return

    discovered_ids = {d["id"] for d in deployments}
    for dep in deployments:
        existing = await fetch_one("SELECT id FROM deployments WHERE id = ?", (dep["id"],))
        if existing:
            await execute(
                """UPDATE deployments SET
                    slug=?, environment=?, git_url=?, health_url=?, browser_url=?,
                    expected_selector=?, tcp_checks=?, container_id=?, container_name=?,
                    image=?, status=?, last_check=?
                WHERE id=?""",
                (
                    dep["slug"], dep["environment"], dep["git_url"], dep["health_url"],
                    dep["browser_url"], dep["expected_selector"], dep["tcp_checks"],
                    dep["container_id"], dep["container_name"], dep["image"],
                    dep["status"], datetime.utcnow().isoformat(), dep["id"],
                ),
            )
        else:
            await execute(
                """INSERT INTO deployments
                    (id, slug, environment, git_url, health_url, browser_url,
                     expected_selector, tcp_checks, container_id, container_name,
                     image, status, last_check)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    dep["id"], dep["slug"], dep["environment"], dep["git_url"],
                    dep["health_url"], dep["browser_url"], dep["expected_selector"],
                    dep["tcp_checks"], dep["container_id"], dep["container_name"],
                    dep["image"], dep["status"], datetime.utcnow().isoformat(),
                ),
            )
    logger.info(f"Synced {len(deployments)} deployment(s) from Docker (labels + auto-scan)")

    # Remove SQLite rows for containers that no longer have sre.monitor / were removed
    stored = await fetch_all("SELECT id FROM deployments")
    for row in stored:
        if row["id"] not in discovered_ids:
            logger.info(f"Purging stale deployment no longer in Docker inventory: {row['id']}")
            await purge_deployment_from_db(row["id"])


async def run_health_checks():
    """Run HTTP health checks for all deployments."""
    deployments = await fetch_all("SELECT * FROM deployments")

    for dep in deployments:
        health_url = dep.get("health_url")
        if not health_url:
            continue

        result = await http_health_check(health_url)

        await execute(
            """INSERT INTO health_checks (deployment_id, check_type, status_code, response_time_ms, success, error_message, checked_at)
            VALUES (?, 'http', ?, ?, ?, ?, ?)""",
            (
                dep["id"],
                result.get("status_code"),
                result.get("response_time_ms"),
                1 if result.get("success") else 0,
                result.get("error_message"),
                datetime.utcnow().isoformat(),
            ),
        )

        new_status = "healthy" if result.get("success") else "unhealthy"
        await execute(
            "UPDATE deployments SET status=?, last_check=? WHERE id=?",
            (new_status, datetime.utcnow().isoformat(), dep["id"]),
        )

        await detect_health_incidents(dep["id"], result)

    logger.info(f"Health checks completed for {len(deployments)} deployments")


async def run_container_checks():
    """Collect container metrics and detect container-related incidents."""
    if DEMO_MODE:
        from app.workers.demo import run_demo_container_checks
        await run_demo_container_checks()
        return

    deployments = await fetch_all("SELECT * FROM deployments WHERE container_id IS NOT NULL")

    for dep in deployments:
        metrics = collect_container_metrics(dep["container_id"])
        if metrics is None:
            await create_or_update_incident(
                deployment_id=dep["id"],
                title="Docker metrics collection failed",
                severity="warning",
                trigger_type="infrastructure",
                error_category="docker_socket_failure",
                suggested_fix=SUGGESTED_FIXES["docker_socket_failure"],
                fingerprint=make_fingerprint(dep["id"], "docker_socket_failure"),
            )
            continue

        await execute(
            """INSERT INTO container_metrics
                (deployment_id, container_state, restart_count, exit_code,
                 cpu_percent, memory_usage_mb, memory_limit_mb,
                 network_rx_bytes, network_tx_bytes, collected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                dep["id"],
                metrics["container_state"],
                metrics["restart_count"],
                metrics["exit_code"],
                metrics["cpu_percent"],
                metrics["memory_usage_mb"],
                metrics["memory_limit_mb"],
                metrics["network_rx_bytes"],
                metrics["network_tx_bytes"],
                datetime.utcnow().isoformat(),
            ),
        )

        await detect_container_incidents(dep["id"], metrics)

    logger.info(f"Container checks completed for {len(deployments)} deployments")


async def run_tcp_checks_worker():
    """Run TCP checks for all deployments with tcp_checks configured."""
    deployments = await fetch_all("SELECT * FROM deployments WHERE tcp_checks IS NOT NULL AND tcp_checks != ''")

    for dep in deployments:
        tcp_str = dep.get("tcp_checks", "")
        if not tcp_str:
            continue

        results = await run_tcp_checks(tcp_str)
        for result in results:
            await execute(
                """INSERT INTO tcp_checks (deployment_id, host, port, success, error_message, checked_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    dep["id"],
                    result["host"],
                    result["port"],
                    1 if result["success"] else 0,
                    result.get("error_message"),
                    datetime.utcnow().isoformat(),
                ),
            )

        await detect_tcp_incidents(dep["id"], results)

    logger.info(f"TCP checks completed for {len(deployments)} deployments")


async def run_browser_checks():
    """Run browser checks for all deployments with browser_url configured."""
    deployments = await fetch_all("SELECT * FROM deployments WHERE browser_url IS NOT NULL AND browser_url != ''")

    for dep in deployments:
        url = dep.get("browser_url")
        if not url:
            continue

        result = await browser_check(url, dep.get("expected_selector"))

        await execute(
            """INSERT INTO browser_checks
                (deployment_id, url, status_code, selector_found, page_blank, error_message, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                dep["id"],
                url,
                result.get("status_code"),
                1 if result.get("selector_found") else 0,
                1 if result.get("page_blank") else 0,
                result.get("error_message"),
                datetime.utcnow().isoformat(),
            ),
        )

        await detect_browser_incidents(dep["id"], result, dep.get("expected_selector", ""))

    logger.info(f"Browser checks completed for {len(deployments)} deployments")


async def run_infra_checks():
    """Collect VPS metadata and Docker sizes."""
    if DEMO_MODE:
        from app.workers.demo import run_demo_infra_checks
        await run_demo_infra_checks()
        return

    vps = collect_vps_metadata()
    await execute(
        """INSERT INTO vps_metadata
            (target_id, os_name, kernel, docker_version, cpu_count, memory_total_mb, disk_total_gb, disk_used_gb, collected_at)
        VALUES ('local', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            vps["os_name"], vps["kernel"], vps["docker_version"],
            vps["cpu_count"], vps["memory_total_mb"],
            vps["disk_total_gb"], vps["disk_used_gb"],
            datetime.utcnow().isoformat(),
        ),
    )

    sizes = collect_docker_sizes()
    await execute(
        """INSERT INTO docker_sizes
            (target_id, images_mb, containers_mb, volumes_mb, build_cache_mb, collected_at)
        VALUES ('local', ?, ?, ?, ?, ?)""",
        (
            sizes["images_mb"], sizes["containers_mb"],
            sizes["volumes_mb"], sizes["build_cache_mb"],
            datetime.utcnow().isoformat(),
        ),
    )

    await detect_disk_pressure(vps, "local")

    logger.info("Infrastructure checks completed")


async def run_traefik_checks():
    """Parse Traefik logs and detect user-facing errors."""
    entries = collect_traefik_logs()
    if not entries:
        logger.debug("No Traefik log entries found")
        return

    # Store recent entries
    for entry in entries[-200:]:  # limit to recent
        await execute(
            """INSERT INTO traefik_logs
                (deployment_id, method, path, status_code, duration_ms, upstream, remote_ip, logged_at, raw_line)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                None,
                entry.get("method"),
                entry.get("path"),
                entry.get("status_code"),
                entry.get("duration_ms"),
                entry.get("upstream"),
                entry.get("remote_ip"),
                entry.get("logged_at"),
                entry.get("raw_line"),
            ),
        )

    # Detect user errors
    user_errors = categorize_user_errors(entries)
    for err in user_errors:
        existing = await fetch_one(
            "SELECT id, count FROM user_errors WHERE path = ? AND status_code = ? AND method = ?",
            (err["path"], err["status_code"], err.get("method", "")),
        )
        if existing:
            new_count = existing["count"] + err["count"]
            await execute(
                "UPDATE user_errors SET count = ?, last_seen = ? WHERE id = ?",
                (new_count, err.get("last_seen"), existing["id"]),
            )
        else:
            await execute(
                """INSERT INTO user_errors (deployment_id, path, method, status_code, error_category, count, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    None, err["path"], err.get("method", ""),
                    err["status_code"], err.get("error_category"),
                    err["count"], err.get("first_seen"), err.get("last_seen"),
                ),
            )

    # Detect Traefik incidents
    traefik_incidents = detect_traefik_incidents(entries)
    for inc in traefik_incidents:
        await create_or_update_incident(
            deployment_id="_traefik",
            title=inc["title"],
            severity=inc["severity"],
            trigger_type="traefik_log",
            error_category=inc["error_category"],
            suggested_fix=inc["suggested_fix"],
            fingerprint=make_fingerprint("_traefik", f"traefik_{inc['path']}_{inc['error_category']}", inc["path"]),
        )

    logger.info(f"Traefik checks: {len(entries)} entries, {len(user_errors)} error categories, {len(traefik_incidents)} incidents")


async def run_all_checks():
    """Run all monitoring checks."""
    try:
        await sync_deployments()
    except Exception as e:
        logger.error(f"sync_deployments failed: {e}")

    try:
        await run_health_checks()
    except Exception as e:
        logger.error(f"run_health_checks failed: {e}")

    try:
        await run_container_checks()
    except Exception as e:
        logger.error(f"run_container_checks failed: {e}")

    try:
        await run_tcp_checks_worker()
    except Exception as e:
        logger.error(f"run_tcp_checks_worker failed: {e}")

    try:
        await run_infra_checks()
    except Exception as e:
        logger.error(f"run_infra_checks failed: {e}")

    try:
        await run_traefik_checks()
    except Exception as e:
        logger.error(f"run_traefik_checks failed: {e}")

    # Browser checks are less frequent - run every other cycle
    # (they're slow and resource-intensive)
    try:
        await run_browser_checks()
    except Exception as e:
        logger.error(f"run_browser_checks failed: {e}")


def start_scheduler():
    """Start the background monitoring scheduler."""
    scheduler.add_job(run_all_checks, "interval", seconds=CHECK_INTERVAL, id="monitor_all")
    scheduler.start()
    logger.info(f"Scheduler started with interval {CHECK_INTERVAL}s")
