"""Tests for the Traefik access log parser."""
import json
import pytest
from app.collectors.traefik_parser import (
    parse_traefik_access_log,
    categorize_user_errors,
    detect_traefik_incidents,
    _error_category,
    _traefik_fix,
)


class TestTraefikParsing:
    def test_parse_json_format(self):
        line = json.dumps({
            "level": "info",
            "time": "2026-05-16T12:00:01Z",
            "request_Method": "GET",
            "request_Path": "/api/v1/users",
            "request_Protocol": "HTTP/1.1",
            "origin_Status": 404,
            "duration": 12000000,
            "service_name": "api-svc",
            "client_addr": "10.0.0.1:54321",
        })
        result = parse_traefik_access_log(line)
        assert result is not None
        assert result["method"] == "GET"
        assert result["path"] == "/api/v1/users"
        assert result["status_code"] == 404
        assert result["upstream"] == "api-svc"

    def test_parse_common_log_format(self):
        line = '10.0.0.1 - - [16/May/2026:12:00:01 +0000] "GET /index.html HTTP/1.1" 200 2326'
        result = parse_traefik_access_log(line)
        assert result is not None
        assert result["method"] == "GET"
        assert result["path"] == "/index.html"
        assert result["status_code"] == 200
        assert result["remote_ip"] == "10.0.0.1"

    def test_parse_empty_line(self):
        assert parse_traefik_access_log("") is None
        assert parse_traefik_access_log("   ") is None

    def test_parse_invalid_line(self):
        assert parse_traefik_access_log("not a valid log line at all") is None

    def test_parse_truncates_raw_line(self):
        long_line = json.dumps({"request_Method": "GET", "request_Path": "/" + "x" * 1000, "origin_Status": 200})
        result = parse_traefik_access_log(long_line)
        assert result is not None
        assert len(result["raw_line"]) <= 500


class TestErrorCategorization:
    def test_error_category_404(self):
        assert _error_category(404) == "not_found"

    def test_error_category_401(self):
        assert _error_category(401) == "unauthorized"

    def test_error_category_403(self):
        assert _error_category(403) == "forbidden"

    def test_error_category_500(self):
        assert _error_category(500) == "internal_error"

    def test_error_category_502(self):
        assert _error_category(502) == "bad_gateway"

    def test_error_category_503(self):
        assert _error_category(503) == "service_unavailable"

    def test_error_category_504(self):
        assert _error_category(504) == "gateway_timeout"

    def test_error_category_unknown(self):
        assert _error_category(418) == "client_error"
        assert _error_category(599) == "server_error"
        assert _error_category(200) == "unknown"


class TestCategorizeUserErrors:
    def test_groups_4xx_errors(self):
        entries = [
            {"method": "GET", "path": "/api/users", "status_code": 404, "logged_at": "2026-01-01T00:00:00Z", "upstream": "api"},
            {"method": "GET", "path": "/api/users", "status_code": 404, "logged_at": "2026-01-01T00:01:00Z", "upstream": "api"},
            {"method": "GET", "path": "/api/users", "status_code": 200, "logged_at": "2026-01-01T00:02:00Z", "upstream": "api"},
        ]
        result = categorize_user_errors(entries)
        assert len(result) == 1
        assert result[0]["count"] == 2
        assert result[0]["error_category"] == "not_found"

    def test_skips_success_codes(self):
        entries = [
            {"method": "GET", "path": "/", "status_code": 200, "logged_at": "2026-01-01T00:00:00Z"},
            {"method": "GET", "path": "/health", "status_code": 204, "logged_at": "2026-01-01T00:01:00Z"},
        ]
        result = categorize_user_errors(entries)
        assert len(result) == 0

    def test_separates_different_status_codes(self):
        entries = [
            {"method": "GET", "path": "/api", "status_code": 404, "logged_at": "2026-01-01T00:00:00Z"},
            {"method": "GET", "path": "/api", "status_code": 500, "logged_at": "2026-01-01T00:01:00Z"},
        ]
        result = categorize_user_errors(entries)
        assert len(result) == 2


class TestDetectTraefikIncidents:
    def test_detects_repeated_404(self):
        entries = []
        for i in range(6):
            entries.append({
                "method": "GET",
                "path": "/missing-page",
                "status_code": 404,
                "logged_at": f"2026-01-01T00:{i:02d}:00Z",
                "upstream": "web",
            })
        incidents = detect_traefik_incidents(entries, threshold=5)
        assert len(incidents) == 1
        assert incidents[0]["error_category"] == "not_found"
        assert "404" in incidents[0]["title"]

    def test_detects_repeated_5xx(self):
        entries = []
        for i in range(5):
            entries.append({
                "method": "GET",
                "path": "/api/broken",
                "status_code": 500,
                "logged_at": f"2026-01-01T00:{i:02d}:00Z",
                "upstream": "api",
            })
        incidents = detect_traefik_incidents(entries, threshold=5)
        assert len(incidents) == 1
        assert incidents[0]["severity"] == "critical"

    def test_no_incident_below_threshold(self):
        entries = [
            {"method": "GET", "path": "/rare-404", "status_code": 404, "logged_at": "2026-01-01T00:00:00Z"},
        ]
        incidents = detect_traefik_incidents(entries, threshold=5)
        assert len(incidents) == 0


class TestTraefikFix:
    def test_fix_404(self):
        fix = _traefik_fix(404, "/missing")
        assert "router rule" in fix or "fallback" in fix or "static asset" in fix

    def test_fix_502(self):
        fix = _traefik_fix(502, "/api")
        assert "upstream" in fix.lower() or "backend" in fix.lower()

    def test_fix_504(self):
        fix = _traefik_fix(504, "/slow")
        assert "timeout" in fix.lower() or "responding" in fix.lower()
