"""Tests for Docker auto-discovery helpers."""
import pytest
from app.collectors.docker_collector import extract_tcp_host_bindings, extract_exposed_tcp_ports


class TestExtractTcpHostBindings:
    def test_running_container_publish_map(self):
        attrs = {
            "NetworkSettings": {
                "Ports": {
                    "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
                }
            },
            "HostConfig": {"PortBindings": {}},
        }
        assert extract_tcp_host_bindings(attrs) == [(8080, 80)]

    def test_multiple_ports_sorted_processing_order_not_here(self):
        attrs = {
            "NetworkSettings": {
                "Ports": {
                    "3000/tcp": [{"HostIp": "::", "HostPort": "3000"}],
                    "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "9080"}],
                }
            },
            "HostConfig": {"PortBindings": {}},
        }
        got = extract_tcp_host_bindings(attrs)
        assert set(got) == {(3000, 3000), (9080, 80)}

    def test_fallback_hostconfig_when_network_empty(self):
        attrs = {
            "NetworkSettings": {"Ports": {}},
            "HostConfig": {
                "PortBindings": {
                    "8080/tcp": [{"HostIp": "", "HostPort": "18080"}],
                }
            },
        }
        assert extract_tcp_host_bindings(attrs) == [(18080, 8080)]

    def test_skip_mysql_host_port(self):
        attrs = {
            "NetworkSettings": {
                "Ports": {"3306/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3306"}]}
            },
            "HostConfig": {"PortBindings": {}},
        }
        assert extract_tcp_host_bindings(attrs) == []


class TestExtractExposedTcpPorts:
    def test_exposed(self):
        attrs = {"Config": {"ExposedPorts": {"80/tcp": {}, "443/tcp": {}}}}
        got = extract_exposed_tcp_ports(attrs)
        assert set(got) == {80, 443}
