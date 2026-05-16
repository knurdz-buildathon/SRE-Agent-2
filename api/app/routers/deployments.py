from fastapi import APIRouter, Query
from app.models.database import fetch_all, fetch_one

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


@router.get("/{deployment_id}/health")
async def get_deployment_health(deployment_id: str, limit: int = Query(50, ge=1, le=500)):
    checks = await fetch_all(
        """SELECT id, deployment_id, check_type, status_code, response_time_ms, success, error_message, checked_at
        FROM health_checks
        WHERE deployment_id = ?
        ORDER BY checked_at DESC LIMIT ?""",
        (deployment_id, limit),
    )
    return checks


@router.get("/{deployment_id}/errors")
async def get_deployment_errors(deployment_id: str):
    errors = await fetch_all(
        """SELECT id, deployment_id, check_type, status_code, error_message, checked_at
        FROM health_checks
        WHERE deployment_id = ? AND success = 0
        ORDER BY checked_at DESC LIMIT 100""",
        (deployment_id,),
    )
    return errors


@router.get("/{deployment_id}/stats")
async def get_deployment_stats(deployment_id: str, hours: int = Query(24, ge=1, le=720)):
    metrics = await fetch_all(
        """SELECT cpu_percent, memory_usage_mb, memory_limit_mb, network_rx_bytes, network_tx_bytes, collected_at
        FROM container_metrics
        WHERE deployment_id = ? AND collected_at >= datetime('now', ? || ' hours')
        ORDER BY collected_at DESC LIMIT 500""",
        (deployment_id, f"-{hours}"),
    )
    return metrics


@router.get("/{deployment_id}/uptime")
async def get_deployment_uptime(deployment_id: str, days: int = Query(30, ge=1, le=365)):
    rows = await fetch_all(
        """SELECT
            DATE(checked_at) as date,
            COUNT(*) as total,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as ok
        FROM health_checks
        WHERE deployment_id = ? AND checked_at >= datetime('now', ? || ' days')
        GROUP BY DATE(checked_at)
        ORDER BY date""",
        (deployment_id, f"-{days}"),
    )
    return [
        {
            "date": r["date"],
            "uptime_percent": round((r["ok"] / r["total"]) * 100, 1) if r["total"] > 0 else 0,
            "total_checks": r["total"],
            "successful_checks": r["ok"],
        }
        for r in rows
    ]


@router.get("/{deployment_id}/env-issues")
async def get_deployment_env_issues(deployment_id: str):
    incidents = await fetch_all(
        """SELECT id, title, severity, status, error_category, suggested_fix, started_at, resolved_at
        FROM incidents
        WHERE deployment_id = ? AND error_category IN ('likely_env_config_issue', 'container_restarting', 'container_not_running')
        ORDER BY started_at DESC LIMIT 50""",
        (deployment_id,),
    )
    return incidents


@router.get("/{deployment_id}/user-errors")
async def get_deployment_user_errors(deployment_id: str):
    errors = await fetch_all(
        """SELECT source, path, method, status_code, error_category, count, first_seen, last_seen
        FROM user_errors
        WHERE deployment_id = ? OR deployment_id IS NULL
        ORDER BY count DESC LIMIT 50""",
        (deployment_id,),
    )
    return errors
