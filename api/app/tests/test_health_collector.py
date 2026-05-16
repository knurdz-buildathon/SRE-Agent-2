"""Tests for the health check collector."""
import pytest
from app.collectors import health_collector as hc
from app.collectors.health_collector import http_health_check, tcp_check, run_tcp_checks


class TestExpandProbeCandidates:
    def test_non_root_url_no_extra_paths(self):
        assert hc._expand_probe_candidates("http://x:8080/api/health") == [
            "http://x:8080/api/health"
        ]

    def test_root_url_includes_fallback_paths(self):
        out = hc._expand_probe_candidates("http://x:8080/")
        assert out[0] == "http://x:8080/"
        assert "http://x:8080/health" in out
        assert len(out) >= 2


class TestHTTPHealthCheck:
    @pytest.mark.asyncio
    async def test_no_url_returns_failure(self):
        result = await http_health_check("")
        assert result["success"] is False
        assert "No health URL" in result["error_message"]

    @pytest.mark.asyncio
    async def test_invalid_url_returns_failure(self):
        result = await http_health_check("http://nonexistent-host-that-does-not-exist.invalid/health")
        assert result["success"] is False
        assert result["error_message"] is not None


class TestTCPCheck:
    @pytest.mark.asyncio
    async def test_invalid_host_returns_failure(self):
        result = await tcp_check("nonexistent-host-invalid", 9999)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_refused_port(self):
        # Port 1 is almost certainly not listening
        result = await tcp_check("127.0.0.1", 1)
        assert result["success"] is False


class TestRunTCPChecks:
    @pytest.mark.asyncio
    async def test_empty_string(self):
        results = await run_tcp_checks("")
        assert results == []

    @pytest.mark.asyncio
    async def test_none_input(self):
        results = await run_tcp_checks(None)
        assert results == []

    @pytest.mark.asyncio
    async def test_invalid_format(self):
        results = await run_tcp_checks("no-port-specified")
        assert results == []

    @pytest.mark.asyncio
    async def test_valid_format(self):
        results = await run_tcp_checks("127.0.0.1:1")
        assert len(results) == 1
        assert results[0]["host"] == "127.0.0.1"
        assert results[0]["port"] == 1
        assert results[0]["success"] is False

    @pytest.mark.asyncio
    async def test_multiple_entries(self):
        results = await run_tcp_checks("127.0.0.1:1, 127.0.0.1:2")
        assert len(results) == 2
