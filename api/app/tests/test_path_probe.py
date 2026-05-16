"""Tests for auto-discovery health path selection."""
from app.collectors.path_probe import replace_url_path, select_health_url


def test_replace_url_path():
    assert replace_url_path("http://127.0.0.1:8000/", "/health") == "http://127.0.0.1:8000/health"
    assert replace_url_path("http://127.0.0.1:8000/foo?x=1", "ready") == "http://127.0.0.1:8000/ready"


def test_selects_working_health_path_before_root():
    statuses = {
        "http://127.0.0.1:8000/health": 200,
        "http://127.0.0.1:8000/": 404,
    }

    selected = select_health_url(
        "http://127.0.0.1:8000",
        probe_func=lambda url, host: statuses.get(url, 404),
    )

    assert selected == "http://127.0.0.1:8000/health"


def test_explicit_path_skips_probe():
    selected = select_health_url(
        "http://example.test:8080",
        explicit_path="api/ready",
        probe_func=lambda url, host: 500,
    )

    assert selected == "http://example.test:8080/api/ready"


def test_falls_back_to_root_when_no_good_path():
    selected = select_health_url(
        "http://127.0.0.1:8000",
        probe_func=lambda url, host: 404,
    )

    assert selected == "http://127.0.0.1:8000/"
