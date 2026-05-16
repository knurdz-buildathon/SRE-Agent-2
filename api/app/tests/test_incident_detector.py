"""Tests for the incident detection engine."""
import pytest
from app.engines.incident_detector import (
    make_fingerprint,
    SUGGESTED_FIXES,
)


class TestFingerprinting:
    def test_deterministic_fingerprint(self):
        fp1 = make_fingerprint("app1", "http_health_failure")
        fp2 = make_fingerprint("app1", "http_health_failure")
        assert fp1 == fp2

    def test_different_fingerprints_for_different_categories(self):
        fp1 = make_fingerprint("app1", "http_health_failure")
        fp2 = make_fingerprint("app1", "container_not_running")
        assert fp1 != fp2

    def test_different_fingerprints_for_different_deployments(self):
        fp1 = make_fingerprint("app1", "http_health_failure")
        fp2 = make_fingerprint("app2", "http_health_failure")
        assert fp1 != fp2

    def test_fingerprint_with_detail(self):
        fp1 = make_fingerprint("app1", "tcp_failure", "db:3306")
        fp2 = make_fingerprint("app1", "tcp_failure", "redis:6379")
        assert fp1 != fp2

    def test_fingerprint_length(self):
        fp = make_fingerprint("app1", "http_health_failure")
        assert len(fp) == 16


class TestSuggestedFixes:
    def test_all_categories_have_fixes(self):
        expected_categories = [
            "container_not_running",
            "container_restarting",
            "http_health_failure",
            "http_timeout",
            "http_5xx",
            "missing_selector",
            "page_blank",
            "high_cpu",
            "high_memory",
            "tcp_dependency_failure",
            "docker_socket_failure",
            "disk_pressure",
            "likely_env_config_issue",
        ]
        for cat in expected_categories:
            assert cat in SUGGESTED_FIXES, f"Missing fix for category: {cat}"

    def test_fixes_are_descriptive(self):
        for cat, fix in SUGGESTED_FIXES.items():
            assert len(fix) > 20, f"Fix for {cat} is too short"
            assert "check" in fix.lower() or "verify" in fix.lower() or "consider" in fix.lower(), \
                f"Fix for {cat} should be actionable"
