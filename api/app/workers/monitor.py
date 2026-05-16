import asyncio
import logging
import os
from datetime import datetime
from urllib.parse import urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.models.database import execute, fetch_one, fetch_all
from app.collectors.docker_collector import (
    discover_deployments,
    collect_container_metrics,
    collect_vps_metadata,
    collect_docker_sizes,
)
from app.collectors.vps_scanner import discover_vps_deployments
from app.collectors.health_collector import http_health_check, run_tcp_checks
from app.collectors.browser_collector import browser_check
from app.collectors.log_reader import read_new_log_entries
from app.collectors.traefik_parser import (
    TRAEFIK_LOG_DIR,
    parse_traefik_access_log,
    categorize_user_errors,
    detect_traefik_incidents,
)
from app.collectors.user_log_parser import USER_LOG_DIR, parse_user_log_line
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
LOG_MAX_BYTES_PER_FILE = int(os.getenv("LOG_MAX_BYTES_PER_FILE", "2000000"))


def _health_failure_threshold() -> int:
    try:
        return max(1, int(os.getenv("HEALTH_DOWN_AFTER_FAILURES", "3")))
    except ValueError:
        return 3

scheduler = AsyncIOScheduler()


def _probe_host_header(dep: dict):
    h = dep.get("probe_host_header")
    if h is None:
        return None
    s = str(h).strip()
    return s or None


async def _load_log_offsets(source: str) -> dict:
    rows = await fetch_all(
        "SELECT file_path, offset FROM log_ingest_state WHERE source = ?",
        (source,),
    )
    return {row["file_path"]: int(row.get("offset") or 0) for row in rows}


async def _save_log_offsets(source: str, offsets: dict):
    now = datetime.utcnow().isoformat()
    for file_path, offset in offsets.items():
        await execute(
            """INSERT INTO log_ingest_state (source, file_path, offset, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, file_path) DO UPDATE SET offset = excluded.offset, updated_at = excluded.updated_at""",
            (source, file_path, int(offset or 0), now),
        )


def _deployment_lookup(deployments: list) -> dict:
    lookup = {}
    for dep in deployments:
        for key in (
            dep.get("id"),
            dep.get("slug"),
            dep.get("container_name"),
            dep.get("image"),
        ):
            if key:
                lookup[str(key).lower()] = dep["id"]
    return lookup


def _attach_deployment_ids(entries: list, deployments: list) -> list:
    lookup = _deployment_lookup(deployments)
    if not lookup:
        return entries

    for entry in entries:
        if entry.get("deployment_id"):
            continue
        candidates = [
            entry.get("upstream"),
            entry.get("service"),
            entry.get("source_file"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            normalized = str(candidate).lower()
            if normalized in lookup:
                entry["deployment_id"] = lookup[normalized]
                break
            for known, deployment_id in lookup.items():
                if known and known in normalized:
                    entry["deployment_id"] = deployment_id
                    break
            if entry.get("deployment_id"):
                break
    return entries


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

    # Collect Docker host-port set so VPS scanner skips ports Docker already covers
    docker_host_ports: set = set()
    for dep in deployments:
        hu = dep.get("health_url") or ""
        if not hu:
            continue
        try:
            parsed = urlparse(hu)
            port = parsed.port
            if port is None and parsed.scheme in ("http", "https"):
                port = 443 if parsed.scheme == "https" else 80
            if port:
                docker_host_ports.add(port)
        except Exception:
            pass

    # Merge VPS-scanned deployments (non-Docker listeners + vhost hostnames)
    vps_deployments = discover_vps_deployments(docker_host_ports)
    deployments = deployments + vps_deployments

    discovered_ids = {d["id"] for d in deployments}
    for dep in deployments:
        existing = await fetch_one("SELECT id FROM deployments WHERE id = ?", (dep["id"],))
        if existing:
            await execute(
                """UPDATE deployments SET
                    slug=?, environment=?, git_url=?, health_url=?, browser_url=?,
                    expected_selector=?, tcp_checks=?, probe_host_header=?, container_id=?, container_name=?,
                    image=?, status=?, source=?, vhost_names=?, last_check=?
                WHERE id=?""",
                (
                    dep["slug"], dep["environment"], dep["git_url"], dep["health_url"],
                    dep["browser_url"], dep["expected_selector"], dep["tcp_checks"],
                    dep.get("probe_host_header"),
                    dep.get("container_id"), dep.get("container_name"), dep.get("image"),
                    dep["status"], dep.get("source", "docker"),
                    ",".join(dep.get("vhost_names") or []) if dep.get("vhost_names") else None,
                    datetime.utcnow().isoformat(), dep["id"],
                ),
            )
        else:
            await execute(
                """INSERT INTO deployments
                    (id, slug, environment, git_url, health_url, browser_url,
                     expected_selector, tcp_checks, probe_host_header, container_id, container_name,
                     image, status, source, vhost_names, last_check)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    dep["id"], dep["slug"], dep["environment"], dep["git_url"],
                    dep["health_url"], dep["browser_url"], dep["expected_selector"],
                    dep["tcp_checks"], dep.get("probe_host_header"),
                    dep.get("container_id"), dep.get("container_name"),
                    dep.get("image"), dep["status"],
                    dep.get("source", "docker"),
                    ",".join(dep.get("vhost_names") or []) if dep.get("vhost_names") else None,
                    datetime.utcnow().isoformat(),
                ),
            )
    logger.info(f"Synced {len(deployments)} deployment(s) (Docker labels + auto-scan + VPS scan)")

    # Remove SQLite rows no longer returned by discovery (Docker + VPS scan)
    stored = await fetch_all("SELECT id FROM deployments")
    for row in stored:
        if row["id"] not in discovered_ids:
            logger.info(f"Purging stale deployment no longer in inventory: {row['id']}")
            await purge_deployment_from_db(row["id"])


async def run_health_checks():
    """Run HTTP health checks for all deployments."""
    deployments = await fetch_all("SELECT * FROM deployments")
    need_failures = _health_failure_threshold()

    for dep in deployments:
        health_url = dep.get("health_url")
        if not health_url:
            continue

        prev_status = dep.get("status") or "unknown"

        result = await http_health_check(health_url, _probe_host_header(dep))

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

        if result.get("success"):
            new_status = "up"
        else:
            recent = await fetch_all(
                """SELECT success FROM health_checks WHERE deployment_id = ? AND check_type = 'http'
                   ORDER BY checked_at DESC LIMIT ?""",
                (dep["id"], need_failures),
            )
            consec_fail = 0
            for row in recent:
                if row["success"]:
                    break
                consec_fail += 1
            if consec_fail >= need_failures:
                new_status = "down"
            else:
                new_status = prev_status

        await execute(
            "UPDATE deployments SET status=?, last_check=? WHERE id=?",
            (new_status, datetime.utcnow().isoformat(), dep["id"]),
        )

        if result.get("success"):
            await detect_health_incidents(dep["id"], result)
        elif new_status == "down" and prev_status != "down":
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


async def _upsert_user_error(err: dict):
    deployment_key = err.get("deployment_id") or ""
    source = err.get("source") or "traefik"
    method = err.get("method", "")
    existing = await fetch_one(
        """SELECT id, count FROM user_errors
        WHERE path = ? AND status_code = ? AND method = ? AND source = ? AND COALESCE(deployment_id, '') = ?""",
        (err["path"], err["status_code"], method, source, deployment_key),
    )
    if existing:
        new_count = existing["count"] + err["count"]
        await execute(
            "UPDATE user_errors SET count = ?, last_seen = ?, error_category = ? WHERE id = ?",
            (new_count, err.get("last_seen"), err.get("error_category"), existing["id"]),
        )
    else:
        await execute(
            """INSERT INTO user_errors
                (deployment_id, source, path, method, status_code, error_category, count, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                err.get("deployment_id"),
                source,
                err["path"],
                method,
                err["status_code"],
                err.get("error_category"),
                err["count"],
                err.get("first_seen"),
                err.get("last_seen"),
            ),
        )


async def _process_user_error_entries(entries: list, incident_source: str):
    user_errors = categorize_user_errors(entries)
    for err in user_errors:
        await _upsert_user_error(err)

    incidents = detect_traefik_incidents(entries)
    for inc in incidents:
        deployment_id = inc.get("deployment_id") or f"_{incident_source}"
        await create_or_update_incident(
            deployment_id=deployment_id,
            title=inc["title"],
            severity=inc["severity"],
            trigger_type=f"{incident_source}_log",
            error_category=inc["error_category"],
            suggested_fix=inc["suggested_fix"],
            fingerprint=make_fingerprint(
                deployment_id,
                f"{incident_source}_{inc['path']}_{inc['error_category']}",
                inc["path"],
            ),
        )

    return user_errors, incidents


async def run_traefik_checks():
    """Parse new Traefik log lines and detect user-facing errors."""
    offsets = await _load_log_offsets("traefik")
    entries, new_offsets = read_new_log_entries(
        TRAEFIK_LOG_DIR,
        parse_traefik_access_log,
        offsets,
        source="traefik",
        max_bytes_per_file=LOG_MAX_BYTES_PER_FILE,
    )
    if not entries:
        await _save_log_offsets("traefik", new_offsets)
        logger.debug("No new Traefik log entries found")
        return

    deployments = await fetch_all("SELECT id, slug, container_name, image FROM deployments")
    entries = _attach_deployment_ids(entries, deployments)

    for entry in entries[-200:]:
        await execute(
            """INSERT INTO traefik_logs
                (deployment_id, method, path, status_code, duration_ms, upstream, remote_ip, logged_at, raw_line)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("deployment_id"),
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

    user_errors, incidents = await _process_user_error_entries(entries, "traefik")
    await _save_log_offsets("traefik", new_offsets)
    logger.info(
        "Traefik checks: %s new entries, %s error categories, %s incidents",
        len(entries),
        len(user_errors),
        len(incidents),
    )


async def run_user_log_checks():
    """Parse mounted app/user logs and feed the User Errors dashboard."""
    offsets = await _load_log_offsets("user_log")
    entries, new_offsets = read_new_log_entries(
        USER_LOG_DIR,
        parse_user_log_line,
        offsets,
        source="user_log",
        max_bytes_per_file=LOG_MAX_BYTES_PER_FILE,
    )
    if not entries:
        await _save_log_offsets("user_log", new_offsets)
        logger.debug("No new user log entries found")
        return

    deployments = await fetch_all("SELECT id, slug, container_name, image FROM deployments")
    entries = _attach_deployment_ids(entries, deployments)
    user_errors, incidents = await _process_user_error_entries(entries, "user_log")
    await _save_log_offsets("user_log", new_offsets)
    logger.info(
        "User log checks: %s new entries, %s error categories, %s incidents",
        len(entries),
        len(user_errors),
        len(incidents),
    )


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

    try:
        await run_user_log_checks()
    except Exception as e:
        logger.error(f"run_user_log_checks failed: {e}")

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
