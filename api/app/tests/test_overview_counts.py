"""Overview aggregation buckets."""
from app.routers.overview import _aggregate_bucket, _container_status


def test_aggregate_running_not_down():
    assert _aggregate_bucket("running") == "unknown"
    assert _aggregate_bucket("stopped") == "unknown"
    assert _aggregate_bucket(None) == "unknown"


def test_aggregate_explicit_terminal():
    assert _aggregate_bucket("up") == "up"
    assert _aggregate_bucket("healthy") == "up"
    assert _aggregate_bucket("down") == "down"
    assert _aggregate_bucket("unhealthy") == "down"


def test_container_status_normalized():
    assert _container_status("Running") == "running"
    assert _container_status(" restarting ") == "restarting"
    assert _container_status("") is None
