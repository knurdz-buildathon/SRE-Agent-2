import hashlib
import logging
from typing import Optional, Dict, List
from datetime import datetime

from app.models.database import execute, fetch_one, execute_insert

logger = logging.getLogger("sre")

SUGGESTED_FIXES = {
    "container_not_running": "Container is not running. Check docker compose logs, image startup command, required env vars, and build output.",
    "container_restarting": "Container is in a crash loop (restarting). Check `docker compose logs` for the crash reason, verify env vars, and check OOM kills.",
    "http_health_failure": "HTTP health check failed. Check that the service is listening on the expected port, the health endpoint is defined, and no firewall is blocking access.",
    "http_timeout": "HTTP health check timed out. The service may be overloaded, stuck, or unreachable. Check CPU/memory, network, and upstream dependencies.",
    "http_5xx": "HTTP 5xx response from health endpoint. The service is encountering internal errors. Check application logs for stack traces and recent deployments.",
    "http_4xx": "HTTP 4xx response from health endpoint. The health URL may be incorrect or require authentication. Verify the health check path.",
    "browser_render_failure": "Browser check returned an error. The page may not be loading at all. Check if the frontend build was deployed and the web server is serving files correctly.",
    "missing_selector": "Browser check returned HTTP 200 but expected selector is missing. Check frontend JS crash or build artifact path.",
    "page_blank": "Browser check shows a blank page. The frontend may have a build issue, missing JS bundle, or runtime error. Check browser console output.",
    "high_cpu": "Container CPU usage is above 90%. Consider increasing CPU limits, checking for runaway processes, or scaling horizontally.",
    "high_memory": "Container memory usage is above 90%. Consider increasing memory limits, checking for memory leaks, or restarting the container.",
    "tcp_dependency_failure": "TCP check failed for a backing service. The dependency may be down or unreachable. Check that the service container is running and the network is configured.",
    "infra_collection_failure": "Infrastructure metrics collection failed. Check that the Docker socket is mounted read-only, the monitoring container has access to /var/run/docker.sock, and the daemon is reachable.",
    "docker_socket_failure": "Docker socket/API connection failed. Check that the Docker socket is mounted and the container has access.",
    "disk_pressure": "Disk usage is above 85%. Consider pruning unused Docker images, volumes, and build cache, or expanding disk capacity.",
    "likely_env_config_issue": "Container keeps restarting with the same exit code. Likely an environment variable or configuration issue. Check .env file, secrets, and config mounts.",
}


def make_fingerprint(deployment_id: str, error_category: str, detail: str = "") -> str:
    raw = f"{deployment_id}:{error_category}:{detail}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


async def create_or_update_incident(
    deployment_id: str,
    title: str,
    severity: str,
    trigger_type: str,
    error_category: str,
    suggested_fix: str,
    fingerprint: str,
    environment: str = "production",
    detail: str = "",
) -> Optional[int]:
    fp = fingerprint or make_fingerprint(deployment_id, error_category, detail)

    # Check for existing open incident with same fingerprint
    existing = await fetch_one(
        "SELECT id, status FROM incidents WHERE fingerprint = ? AND status = 'open'",
        (fp,),
    )

    if existing:
        # Append timeline event
        await execute(
            "INSERT INTO incident_timeline (incident_id, event_type, message) VALUES (?, 'continued', ?)",
            (existing["id"], f"Issue continues: {title}"),
        )
        logger.info(f"Incident {existing['id']} updated (continues): {title}")
        return existing["id"]

    incident_id = await execute_insert(
        """INSERT INTO incidents (deployment_id, title, severity, status, environment, trigger_type, error_category, fingerprint, suggested_fix)
        VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)""",
        (
            deployment_id,
            title,
            severity,
            environment,
            trigger_type,
            error_category,
            fp,
            suggested_fix,
        ),
    )

    if incident_id:
        await execute(
            "INSERT INTO incident_timeline (incident_id, event_type, message) VALUES (?, 'opened', ?)",
            (incident_id, f"Incident opened: {title}"),
        )
        logger.info(f"New incident {incident_id}: {title}")

    return incident_id


async def resolve_incident(fingerprint: str, message: str = "Health recovered"):
    existing = await fetch_one(
        "SELECT id FROM incidents WHERE fingerprint = ? AND status = 'open'",
        (fingerprint,),
    )
    if existing:
        now = datetime.utcnow().isoformat()
        await execute(
            "UPDATE incidents SET status = 'resolved', resolved_at = ? WHERE id = ?",
            (now, existing["id"]),
        )
        await execute(
            "INSERT INTO incident_timeline (incident_id, event_type, message) VALUES (?, 'resolved', ?)",
            (existing["id"], message),
        )
        logger.info(f"Incident {existing['id']} resolved: {message}")


async def detect_container_incidents(deployment_id: str, metrics: Dict):
    state = metrics.get("container_state", "unknown")
    restart_count = metrics.get("restart_count", 0)
    exit_code = metrics.get("exit_code", 0)

    if state != "running":
        cat = "container_not_running"
        if restart_count > 3:
            cat = "container_restarting"
        elif exit_code != 0:
            cat = "likely_env_config_issue"
        await create_or_update_incident(
            deployment_id=deployment_id,
            title=f"Container {state}" + (f" (exit {exit_code})" if exit_code else ""),
            severity="critical",
            trigger_type="docker",
            error_category=cat,
            suggested_fix=SUGGESTED_FIXES.get(cat, "Check container status and logs."),
            fingerprint=make_fingerprint(deployment_id, cat),
        )
    else:
        # Resolve if was previously not running
        fp = make_fingerprint(deployment_id, "container_not_running")
        await resolve_incident(fp)
        fp = make_fingerprint(deployment_id, "container_restarting")
        await resolve_incident(fp)
        fp = make_fingerprint(deployment_id, "likely_env_config_issue")
        await resolve_incident(fp)

    if restart_count > 3:
        cat = "container_restarting"
        await create_or_update_incident(
            deployment_id=deployment_id,
            title=f"Container restarting ({restart_count} restarts)",
            severity="critical",
            trigger_type="docker",
            error_category=cat,
            suggested_fix=SUGGESTED_FIXES.get(cat, "Check container logs."),
            fingerprint=make_fingerprint(deployment_id, cat),
        )

    cpu = metrics.get("cpu_percent", 0)
    if cpu > 90:
        await create_or_update_incident(
            deployment_id=deployment_id,
            title=f"High CPU usage ({cpu:.1f}%)",
            severity="warning",
            trigger_type="metrics",
            error_category="high_cpu",
            suggested_fix=SUGGESTED_FIXES["high_cpu"],
            fingerprint=make_fingerprint(deployment_id, "high_cpu"),
        )
    else:
        await resolve_incident(make_fingerprint(deployment_id, "high_cpu"))

    mem_pct = 0
    mem_usage = metrics.get("memory_usage_mb", 0)
    mem_limit = metrics.get("memory_limit_mb", 1)
    if mem_limit > 0:
        mem_pct = (mem_usage / mem_limit) * 100

    if mem_pct > 90:
        await create_or_update_incident(
            deployment_id=deployment_id,
            title=f"High memory usage ({mem_pct:.1f}%)",
            severity="warning",
            trigger_type="metrics",
            error_category="high_memory",
            suggested_fix=SUGGESTED_FIXES["high_memory"],
            fingerprint=make_fingerprint(deployment_id, "high_memory"),
        )
    else:
        await resolve_incident(make_fingerprint(deployment_id, "high_memory"))


async def detect_health_incidents(deployment_id: str, result: Dict):
    success = result.get("success", False)
    status_code = result.get("status_code")
    error_message = result.get("error_message", "")

    if success:
        # Resolve previous health incidents
        for cat in ["http_health_failure", "http_timeout", "http_5xx", "http_4xx"]:
            await resolve_incident(make_fingerprint(deployment_id, cat))
        return

    if error_message and "Timeout" in error_message:
        cat = "http_timeout"
        severity = "critical"
    elif status_code and 500 <= status_code < 600:
        cat = "http_5xx"
        severity = "critical"
    elif status_code and 400 <= status_code < 500:
        cat = "http_4xx"
        severity = "warning"
    else:
        cat = "http_health_failure"
        severity = "critical"

    title = f"HTTP health check failed"
    if status_code:
        title += f" (HTTP {status_code})"
    if error_message:
        title += f" - {error_message[:50]}"

    await create_or_update_incident(
        deployment_id=deployment_id,
        title=title,
        severity=severity,
        trigger_type="health_check",
        error_category=cat,
        suggested_fix=SUGGESTED_FIXES.get(cat, "Check health endpoint."),
        fingerprint=make_fingerprint(deployment_id, cat),
    )


async def detect_browser_incidents(deployment_id: str, result: Dict, expected_selector: str = ""):
    success = result.get("success", False)
    selector_found = result.get("selector_found", True)
    page_blank = result.get("page_blank", False)
    error_message = result.get("error_message", "")

    if success:
        for cat in ["browser_render_failure", "missing_selector", "page_blank"]:
            await resolve_incident(make_fingerprint(deployment_id, cat))
        return

    if page_blank:
        cat = "page_blank"
        severity = "critical"
        title = "Browser check shows blank page"
    elif not selector_found and expected_selector:
        cat = "missing_selector"
        severity = "degraded"
        title = f"Missing expected selector '{expected_selector}'"
    else:
        cat = "browser_render_failure"
        severity = "critical"
        title = "Browser check failed"

    if error_message:
        title += f" - {error_message[:50]}"

    await create_or_update_incident(
        deployment_id=deployment_id,
        title=title,
        severity=severity,
        trigger_type="browser_check",
        error_category=cat,
        suggested_fix=SUGGESTED_FIXES.get(cat, "Check browser check configuration."),
        fingerprint=make_fingerprint(deployment_id, cat),
    )


async def detect_tcp_incidents(deployment_id: str, results: List[Dict]):
    for result in results:
        host = result.get("host", "")
        port = result.get("port", 0)
        success = result.get("success", False)

        if not success:
            await create_or_update_incident(
                deployment_id=deployment_id,
                title=f"TCP check failed for {host}:{port}",
                severity="critical",
                trigger_type="tcp_check",
                error_category="tcp_dependency_failure",
                suggested_fix=SUGGESTED_FIXES["tcp_dependency_failure"],
                fingerprint=make_fingerprint(deployment_id, "tcp_dependency_failure", f"tcp_{host}:{port}"),
            )
        else:
            await resolve_incident(
                make_fingerprint(deployment_id, "tcp_dependency_failure", f"tcp_{host}:{port}")
            )


async def detect_disk_pressure(vps_data: Dict, target_id: str = "local"):
    disk_total = vps_data.get("disk_total_gb", 0)
    disk_used = vps_data.get("disk_used_gb", 0)
    if disk_total > 0:
        pct = (disk_used / disk_total) * 100
        if pct > 85:
            await create_or_update_incident(
                deployment_id="_infrastructure",
                title=f"Disk pressure: {pct:.1f}% used ({disk_used:.1f}/{disk_total:.1f} GB)",
                severity="warning",
                trigger_type="infrastructure",
                error_category="disk_pressure",
                suggested_fix=SUGGESTED_FIXES["disk_pressure"],
                fingerprint=make_fingerprint("_infrastructure", "disk_pressure"),
            )
        else:
            await resolve_incident(make_fingerprint("_infrastructure", "disk_pressure"))
