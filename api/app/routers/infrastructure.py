from fastapi import APIRouter
from app.models.database import fetch_all, fetch_one
from app.collectors.docker_collector import get_running_containers

router = APIRouter(prefix="/api", tags=["infrastructure"])


@router.get("/infrastructure")
async def get_infrastructure():
    vps = await fetch_all(
        "SELECT * FROM vps_metadata ORDER BY collected_at DESC LIMIT 10"
    )

    sizes = await fetch_all(
        "SELECT * FROM docker_sizes ORDER BY collected_at DESC LIMIT 10"
    )

    # Latest CPU/Memory metrics per deployment
    latest_metrics = await fetch_all(
        """SELECT cm.deployment_id, d.slug, cm.cpu_percent, cm.memory_usage_mb,
            cm.memory_limit_mb, cm.container_state, cm.restart_count,
            cm.network_rx_bytes, cm.network_tx_bytes, cm.collected_at
        FROM container_metrics cm
        LEFT JOIN deployments d ON cm.deployment_id = d.id
        WHERE cm.id IN (
            SELECT MAX(id) FROM container_metrics GROUP BY deployment_id
        )"""
    )

    containers = get_running_containers()

    # Try to get containers from demo mode if empty
    if not containers:
        from app.collectors.docker_collector import get_docker_client
        client = get_docker_client()
        if not client:
            # In demo mode, provide synthetic container list
            containers = [
                {"name": "sample-healthy-app", "image": "sample-healthy:latest", "status": "running", "slug": "sample-healthy"},
                {"name": "sample-crash-app", "image": "sample-crash:latest", "status": "restarting", "slug": "sample-crash"},
                {"name": "sample-api", "image": "api-service:v2.1", "status": "running", "slug": "sample-api"},
                {"name": "sre-agent-api", "image": "sre-agent-api:latest", "status": "running", "slug": "sre-agent-api"},
                {"name": "sre-agent-web", "image": "sre-agent-web:latest", "status": "running", "slug": ""},
            ]

    return {
        "vps_targets": vps,
        "docker_sizes": sizes,
        "latest_metrics": latest_metrics,
        "containers": containers,
    }
