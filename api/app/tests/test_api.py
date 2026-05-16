"""Tests for the API response shapes."""
import os
import tempfile
from pathlib import Path

os.environ["TEST_MODE"] = "true"
os.environ["DEMO_MODE"] = "false"
os.environ["AUTH_ENABLED"] = "false"
os.environ["DATABASE_PATH"] = str(Path(tempfile.gettempdir()) / "sre_agent_test.db")

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def _init_test_database():
    await init_db()


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_health_endpoint(api_client):
    response = await api_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "sre-agent-api"


@pytest.mark.asyncio
async def test_overview_endpoint(api_client):
    response = await api_client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert "total_deployments" in data
    assert "up_count" in data
    assert "down_count" in data
    assert "unknown_count" in data
    assert "open_incidents" in data
    assert "deployments" in data
    assert isinstance(data["deployments"], list)


@pytest.mark.asyncio
async def test_incidents_endpoint(api_client):
    response = await api_client.get("/api/incidents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_errors_endpoint(api_client):
    response = await api_client.get("/api/errors")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_user_errors_endpoint(api_client):
    response = await api_client.get("/api/user-errors")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_user_errors_summary_endpoint(api_client):
    response = await api_client.get("/api/user-errors/summary")
    assert response.status_code == 200
    data = response.json()
    assert "top_failing_paths" in data
    assert "by_category" in data
    assert "by_status_code" in data


@pytest.mark.asyncio
async def test_infrastructure_endpoint(api_client):
    response = await api_client.get("/api/infrastructure")
    assert response.status_code == 200
    data = response.json()
    assert "vps_targets" in data
    assert "docker_sizes" in data
    assert "latest_metrics" in data
    assert "containers" in data


@pytest.mark.asyncio
async def test_deployment_health_endpoint(api_client):
    response = await api_client.get("/api/deployments/sample-healthy/health")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
