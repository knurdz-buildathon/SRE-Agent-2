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


def _aggregate_bucket(raw: Optional[str]) -> str:
    """Dashboard totals: only explicit down counts as down; running/unknown/etc. are pending."""
    s = _deployment_status(raw)
    if s == "up":
        return "up"
    if s == "down":
        return "down"
    return "unknown"


def _card_display_status(raw: Optional[str]) -> str:
    """Overview cards: collapse non-terminal probe states to unknown (pending)."""
    return _aggregate_bucket(raw)


def _container_status(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    status = str(raw).strip().lower()
    return status or None


@router.get("/overview")
async def get_overview():
    deployments = await fetch_all("SELECT * FROM deployments")

    buckets = [_aggregate_bucket(d.get("status")) for d in deployments]
    up = sum(1 for s in buckets if s == "up")
    down = sum(1 for s in buckets if s == "down")
    unknown = sum(1 for s in buckets if s == "unknown")

    incident_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM incidents WHERE status = 'open'"
    )
    open_incidents = int((incident_row.get("cnt") if incident_row else 0) or 0)

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
        container_row = await fetch_one(
            """SELECT container_state FROM container_metrics
            WHERE deployment_id = ?
            ORDER BY collected_at DESC LIMIT 1""",
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
        if uptime_row:
            total = uptime_row.get("total") or 0
            ok_raw = uptime_row.get("ok")
            if total > 0:
                ok_n = int(ok_raw) if ok_raw is not None else 0
                uptime_pct = round((ok_n / total) * 100, 1)

        site_status = _card_display_status(dep.get("status"))
        container_status = _container_status(
            container_row.get("container_state") if container_row else None
        )
        display_status = container_status or site_status

        cards.append({
            "id": dep["id"],
            "slug": dep.get("slug", dep["id"]),
            "environment": dep.get("environment", "production"),
            "status": display_status,
            "site_status": site_status,
            "container_status": container_status,
            "container_name": dep.get("container_name"),
            "health_url": dep.get("health_url"),
            "uptime_percent": uptime_pct,
            "last_error": last_err.get("error_message") if last_err else None,
            "open_incidents": int((inc_row.get("cnt") if inc_row else 0) or 0),
        })

    return {
        "total_deployments": len(deployments),
        "up_count": up,
        "down_count": down,
        "unknown_count": int(unknown),
        "open_incidents": open_incidents,
        "deployments": cards,
    }
