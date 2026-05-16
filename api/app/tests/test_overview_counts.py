"""Overview aggregation buckets and status convergence."""
from app.routers.overview import _aggregate_bucket, _container_status, _deployment_status, _card_display_status
from app.workers.monitor import _worst_status, _container_state_to_status


def test_aggregate_running_counts_as_up():
    assert _aggregate_bucket("running") == "up"
    assert _aggregate_bucket("up") == "up"
    assert _aggregate_bucket("healthy") == "up"


def test_aggregate_stopped_restarting_counts_as_down():
    assert _aggregate_bucket("stopped") == "down"
    assert _aggregate_bucket("restarting") == "down"
    assert _aggregate_bucket("down") == "down"
    assert _aggregate_bucket("unhealthy") == "down"


def test_aggregate_unknown():
    assert _aggregate_bucket(None) == "unknown"
    assert _aggregate_bucket("unknown") == "unknown"


def test_deployment_status_normalizes_container_states():
    assert _deployment_status("running") == "running"
    assert _deployment_status("Stopped") == "stopped"
    assert _deployment_status("restarting") == "restarting"
    assert _deployment_status("exited") == "stopped"
    assert _deployment_status("dead") == "stopped"
    assert _deployment_status("paused") == "stopped"
    assert _deployment_status("healthy") == "up"
    assert _deployment_status("unhealthy") == "down"


def test_card_display_status_passes_through():
    assert _card_display_status("running") == "running"
    assert _card_display_status("stopped") == "stopped"
    assert _card_display_status("restarting") == "restarting"
    assert _card_display_status("up") == "up"
    assert _card_display_status("down") == "down"


def test_container_status_normalized():
    assert _container_status("Running") == "running"
    assert _container_status(" restarting ") == "restarting"
    assert _container_status("") is None


def test_worst_status():
    assert _worst_status("up", "down") == "down"
    assert _worst_status("running", "down") == "down"
    assert _worst_status("up", "running") == "up"
    assert _worst_status("up", "degraded") == "degraded"
    assert _worst_status("unknown", "up") == "unknown"
    assert _worst_status("running", "restarting") == "restarting"
    assert _worst_status() == "unknown"
    assert _worst_status(None, None) == "unknown"


def test_container_state_to_status():
    assert _container_state_to_status("running") == "running"
    assert _container_state_to_status("stopped") == "stopped"
    assert _container_state_to_status("exited") == "stopped"
    assert _container_state_to_status("dead") == "stopped"
    assert _container_state_to_status("paused") == "stopped"
    assert _container_state_to_status("restarting") == "restarting"
    assert _container_state_to_status("") == "unknown"
