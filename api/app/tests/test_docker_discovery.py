"""Tests for Docker auto-discovery helpers."""
from app.collectors.docker_collector import (
    extract_tcp_host_bindings,
    extract_exposed_tcp_ports,
    extract_traefik_host,
    _health_path_from_labels,
)


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
        # 18080 is not in HTTP_PORTS, so this should return empty
        assert extract_tcp_host_bindings(attrs) == []

    def test_skip_non_http_ports(self):
        """MySQL, Redis, MongoDB etc. are not in HTTP_PORTS — must be excluded."""
        attrs = {
            "NetworkSettings": {
                "Ports": {
                    "3306/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3306"}],
                    "6379/tcp": [{"HostIp": "0.0.0.0", "HostPort": "6379"}],
                    "27017/tcp": [{"HostIp": "0.0.0.0", "HostPort": "27017"}],
                    "5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5432"}],
                }
            },
            "HostConfig": {"PortBindings": {}},
        }
        assert extract_tcp_host_bindings(attrs) == []

    def test_only_http_host_ports_returned(self):
        """Only host ports in HTTP_PORTS should be returned."""
        attrs = {
            "NetworkSettings": {
                "Ports": {
                    "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "80"}],
                    "3306/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3306"}],
                    "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
                    "6379/tcp": [{"HostIp": "0.0.0.0", "HostPort": "6379"}],
                }
            },
            "HostConfig": {"PortBindings": {}},
        }
        got = extract_tcp_host_bindings(attrs)
        host_ports = {hp for hp, _ in got}
        assert host_ports == {80, 8080}
        assert 3306 not in host_ports
        assert 6379 not in host_ports


class TestHealthPathFromLabels:
    def test_default_slash(self):
        assert _health_path_from_labels({}) == "/"

    def test_explicit_relative(self):
        assert _health_path_from_labels({"sre.health_path": "health"}) == "/health"

    def test_explicit_absolute(self):
        assert _health_path_from_labels({"SRE.HEALTH_PATH": "/api/ready"}) == "/api/ready"


class TestExtractTraefikHost:
    def test_host_backticks(self):
        labels = {
            "traefik.http.routers.myapp.rule": "Host(`app.example.com`) && PathPrefix(`/`)",
        }
        assert extract_traefik_host(labels) == "app.example.com"

    def test_host_double_quotes(self):
        labels = {"traefik.http.routers.web.rule": 'Host("www.example.org")'}
        assert extract_traefik_host(labels) == "www.example.org"

    def test_no_rule(self):
        assert extract_traefik_host({"traefik.enable": "true"}) is None


class TestExtractExposedTcpPorts:
    def test_exposed_http_only(self):
        attrs = {"Config": {"ExposedPorts": {"80/tcp": {}, "443/tcp": {}}}}
        got = extract_exposed_tcp_ports(attrs)
        assert set(got) == {80, 443}

    def test_exposed_skips_non_http(self):
        attrs = {"Config": {"ExposedPorts": {"80/tcp": {}, "3306/tcp": {}, "6379/tcp": {}}}}
        got = extract_exposed_tcp_ports(attrs)
        assert set(got) == {80}
