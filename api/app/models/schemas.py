from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class DeploymentBase(BaseModel):
    id: str
    slug: str
    environment: str = "production"
    git_url: Optional[str] = None
    health_url: Optional[str] = None
    browser_url: Optional[str] = None
    expected_selector: Optional[str] = None
    tcp_checks: Optional[str] = None
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    image: Optional[str] = None
    status: str = "unknown"
    last_check: Optional[str] = None


class HealthCheckBase(BaseModel):
    id: int
    deployment_id: str
    check_type: str
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    success: int = 0
    error_message: Optional[str] = None
    checked_at: Optional[str] = None


class TCPCheckBase(BaseModel):
    id: int
    deployment_id: str
    host: str
    port: int
    success: int = 0
    error_message: Optional[str] = None
    checked_at: Optional[str] = None


class BrowserCheckBase(BaseModel):
    id: int
    deployment_id: str
    url: str
    status_code: Optional[int] = None
    selector_found: int = 0
    page_blank: int = 0
    error_message: Optional[str] = None
    checked_at: Optional[str] = None


class ContainerMetricsBase(BaseModel):
    id: int
    deployment_id: str
    container_state: Optional[str] = None
    restart_count: int = 0
    exit_code: Optional[int] = None
    cpu_percent: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    memory_limit_mb: Optional[float] = None
    network_rx_bytes: Optional[int] = None
    network_tx_bytes: Optional[int] = None
    collected_at: Optional[str] = None


class IncidentBase(BaseModel):
    id: int
    deployment_id: Optional[str] = None
    title: str
    severity: str = "warning"
    status: str = "open"
    environment: str = "production"
    trigger_type: Optional[str] = None
    error_category: Optional[str] = None
    fingerprint: Optional[str] = None
    started_at: Optional[str] = None
    resolved_at: Optional[str] = None
    suggested_fix: Optional[str] = None


class IncidentTimelineBase(BaseModel):
    id: int
    incident_id: int
    event_type: str
    message: Optional[str] = None
    occurred_at: Optional[str] = None


class UserErrorBase(BaseModel):
    id: int
    deployment_id: Optional[str] = None
    path: str
    method: Optional[str] = None
    status_code: int
    error_category: Optional[str] = None
    count: int = 1
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


class VPSMetadataBase(BaseModel):
    id: int
    target_id: str
    os_name: Optional[str] = None
    kernel: Optional[str] = None
    docker_version: Optional[str] = None
    cpu_count: Optional[int] = None
    memory_total_mb: Optional[float] = None
    disk_total_gb: Optional[float] = None
    disk_used_gb: Optional[float] = None
    collected_at: Optional[str] = None


class DockerSizesBase(BaseModel):
    id: int
    target_id: str
    images_mb: Optional[float] = None
    containers_mb: Optional[float] = None
    volumes_mb: Optional[float] = None
    build_cache_mb: Optional[float] = None
    collected_at: Optional[str] = None


class OverviewResponse(BaseModel):
    total_deployments: int = 0
    up_count: int = 0
    down_count: int = 0
    open_incidents: int = 0
    deployments: List[dict] = []


class DeploymentCard(BaseModel):
    id: str
    slug: str
    environment: str
    status: str
    uptime_percent: Optional[float] = None
    last_error: Optional[str] = None
    open_incidents: int = 0
