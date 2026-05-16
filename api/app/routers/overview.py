from fastapi import APIRouter
from typing import Optional

from app.models.database import fetch_all, fetch_one

router = APIRouter(prefix="/api", tags=["overview"])


def _deployment_status(raw: Optional[str]) -> str:
    """Normalize legacy healthy/unhealthy rows to up/down."""
    if not raw:
        return "unknown"
    r = raw.lower()
    if r in ("healthy", "up"):
        return "up"
    if r in ("unhealthy", "down"):
        return "down"
    return raw


@router.get("/overview")
async def get_overview():
    deployments = await fetch_all("SELECT * FROM deployments")

    norm = [_deployment_status(d.get("status")) for d in deployments]
    up = sum(1 for s in norm if s == "up")
    down = sum(1 for s in norm if s != "up")

    incident_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM incidents WHERE status = 'open'"
    )
    open_incidents = incident_row["cnt"] if incident_row else 0

    cards = []
    for dep in deployments:
        last_err = await fetch_one(
            "SELECT error_message FROM health_checks WHERE deployment_id = ? AND success = 0 ORDER BY checked_at DESC LIMIT 1",
            (dep["id"],),
        )
        inc_row = await fetch_one(
            "SELECT COUNT(*) as cnt FROM incidents WHERE deployment_id = ? AND status = 'open'",
            (dep["id"],),
        )
        # Calculate uptime from last 24h of checks
        uptime_row = await fetch_one(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as ok
            FROM health_checks
            WHERE deployment_id = ? AND checked_at >= datetime('now', '-1 day')""",
            (dep["id"],),
        )
        uptime_pct = None
        if uptime_row and uptime_row["total"] and uptime_row["total"] > 0:
            uptime_pct = round((uptime_row["ok"] / uptime_row["total"]) * 100, 1)

        cards.append({
            "id": dep["id"],
            "slug": dep.get("slug", dep["id"]),
            "environment": dep.get("environment", "production"),
            "status": _deployment_status(dep.get("status")),
            "uptime_percent": uptime_pct,
            "last_error": last_err["error_message"] if last_err else None,
            "open_incidents": inc_row["cnt"] if inc_row else 0,
        })

    return {
        "total_deployments": len(deployments),
        "up_count": up,
        "down_count": down,
        "open_incidents": open_incidents,
        "deployments": cards,
    }
