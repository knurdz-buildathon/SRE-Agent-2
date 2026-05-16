from fastapi import APIRouter
from app.models.database import fetch_all, fetch_one

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(status: str = None, severity: str = None):
    query = "SELECT * FROM incidents WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if severity:
        query += " AND severity = ?"
        params.append(severity)

    query += " ORDER BY started_at DESC LIMIT 200"
    incidents = await fetch_all(query, tuple(params))

    # Attach timeline for each incident
    result = []
    for inc in incidents:
        timeline = await fetch_all(
            "SELECT id, incident_id, event_type, message, occurred_at FROM incident_timeline WHERE incident_id = ? ORDER BY occurred_at",
            (inc["id"],),
        )
        dep = None
        if inc.get("deployment_id"):
            dep = await fetch_one("SELECT id, slug, environment FROM deployments WHERE id = ?", (inc["deployment_id"],))

        result.append({
            **inc,
            "timeline": timeline,
            "deployment": dep,
        })

    return result


@router.get("/{incident_id}")
async def get_incident(incident_id: int):
    inc = await fetch_one("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    if not inc:
        return {"error": "Incident not found"}

    timeline = await fetch_all(
        "SELECT id, incident_id, event_type, message, occurred_at FROM incident_timeline WHERE incident_id = ? ORDER BY occurred_at",
        (incident_id,),
    )

    dep = None
    if inc.get("deployment_id"):
        dep = await fetch_one("SELECT id, slug, environment FROM deployments WHERE id = ?", (inc["deployment_id"],))

    return {
        **inc,
        "timeline": timeline,
        "deployment": dep,
    }
