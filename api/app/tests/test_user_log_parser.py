"""Tests for generic application/user log parsing."""
import json

from app.collectors.user_log_parser import parse_user_log_line


def test_parse_json_access_log():
    line = json.dumps(
        {
            "timestamp": "2026-05-16T12:00:00Z",
            "method": "POST",
            "path": "/api/orders",
            "status_code": 500,
            "service": "orders-api",
        }
    )

    parsed = parse_user_log_line(line)

    assert parsed is not None
    assert parsed["method"] == "POST"
    assert parsed["path"] == "/api/orders"
    assert parsed["status_code"] == 500
    assert parsed["upstream"] == "orders-api"
    assert parsed["source"] == "user_log"


def test_parse_key_value_log():
    parsed = parse_user_log_line("level=warn method=GET path=/checkout status=404 user_id=123")

    assert parsed is not None
    assert parsed["method"] == "GET"
    assert parsed["path"] == "/checkout"
    assert parsed["status_code"] == 404


def test_parse_error_line_without_status_as_500():
    parsed = parse_user_log_line("ERROR request failed GET /billing/invoices exception=boom")

    assert parsed is not None
    assert parsed["method"] == "GET"
    assert parsed["path"] == "/billing/invoices"
    assert parsed["status_code"] == 500


def test_ignores_non_http_noise():
    assert parse_user_log_line("worker heartbeat ok") is None
