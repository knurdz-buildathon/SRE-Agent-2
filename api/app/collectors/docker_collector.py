import docker
import logging
import os
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("sre")

DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")


def _monitor_label_enabled(labels: dict) -> bool:
    """Accept common truthy label spellings from Compose / Swarm."""
    if not labels:
        return False
    raw = labels.get("sre.monitor")
    if raw is None:
        raw = labels.get("SRE.MONITOR")
    if raw is None:
        return False
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def get_docker_client():
    try:
        client = docker.DockerClient(base_url=f"unix://{DOCKER_SOCKET}")
        client.ping()
        return client
    except Exception as e:
        logger.error(f"Docker socket connection failed: {e}")
        return None


def discover_deployments() -> Tuple[List[Dict], bool]:
    """
    List deployments from Docker labels (sre.monitor=true).

    Returns (deployments, docker_ok). docker_ok is False if the socket/API is
    unreachable — callers must not treat an empty list as "delete everything".
    """
    client = get_docker_client()
    if not client:
        logger.warning("Docker unavailable, skipping deployment discovery")
        return [], False

    deployments = []
    try:
        containers = client.containers.list(all=True)
        for container in containers:
            labels = container.labels or {}
            if not _monitor_label_enabled(labels):
                continue
            slug = labels.get("sre.slug") or labels.get("SRE.SLUG") or container.name
            dep = {
                "id": slug,
                "slug": slug,
                "environment": labels.get("sre.environment") or labels.get("SRE.ENVIRONMENT") or "production",
                "git_url": labels.get("sre.git_url") or labels.get("SRE.GIT_URL"),
                "health_url": labels.get("sre.health_url") or labels.get("SRE.HEALTH_URL"),
                "browser_url": labels.get("sre.browser_url") or labels.get("SRE.BROWSER_URL"),
                "expected_selector": labels.get("sre.expected_selector") or labels.get("SRE.EXPECTED_SELECTOR"),
                "tcp_checks": labels.get("sre.tcp_checks") or labels.get("SRE.TCP_CHECKS"),
                "container_id": container.id,
                "container_name": container.name,
                "image": str(container.image.tags[0]) if container.image.tags else str(container.image.id[:12]),
                "status": "running" if container.status == "running" else "stopped",
            }
            deployments.append(dep)
        return deployments, True
    except Exception as e:
        logger.error(f"Error discovering deployments: {e}")
        return [], False


def collect_container_metrics(container_id: str) -> Optional[Dict]:
    client = get_docker_client()
    if not client:
        return None

    try:
        container = client.containers.get(container_id)
        stats = container.stats(stream=False)

        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        cpu_percent = 0.0
        if system_delta > 0 and cpu_delta > 0:
            cpu_percent = (cpu_delta / system_delta) * 100.0

        mem_usage = stats["memory_stats"].get("usage", 0)
        mem_limit = stats["memory_stats"].get("limit", 0)
        mem_usage_mb = mem_usage / (1024 * 1024) if mem_usage else 0
        mem_limit_mb = mem_limit / (1024 * 1024) if mem_limit else 0

        net_rx = 0
        net_tx = 0
        networks = stats.get("networks", {})
        for iface, data in networks.items():
            net_rx += data.get("rx_bytes", 0)
            net_tx += data.get("tx_bytes", 0)

        # Get restart count from inspection
        inspect = container.attrs
        restart_count = inspect.get("RestartCount", 0)
        exit_code = inspect.get("State", {}).get("ExitCode", 0)
        container_state = inspect.get("State", {}).get("Status", container.status)

        return {
            "container_state": container_state,
            "restart_count": restart_count,
            "exit_code": exit_code,
            "cpu_percent": round(cpu_percent, 2),
            "memory_usage_mb": round(mem_usage_mb, 2),
            "memory_limit_mb": round(mem_limit_mb, 2),
            "network_rx_bytes": net_rx,
            "network_tx_bytes": net_tx,
        }
    except Exception as e:
        logger.error(f"Error collecting metrics for {container_id}: {e}")
        return None


def collect_vps_metadata() -> Dict:
    import platform
    import subprocess

    result = {
        "os_name": f"{platform.system()} {platform.release()}",
        "kernel": platform.version(),
        "docker_version": "unknown",
        "cpu_count": os.cpu_count() or 0,
        "memory_total_mb": 0,
        "disk_total_gb": 0,
        "disk_used_gb": 0,
    }

    # Docker version
    client = get_docker_client()
    if client:
        try:
            ver = client.version()
            result["docker_version"] = ver.get("Version", "unknown")
        except Exception:
            pass

    # Memory
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    result["memory_total_mb"] = round(
                        int(line.split()[1]) / 1024, 2
                    )
                    break
    except Exception:
        pass

    # Disk
    try:
        stat = os.statvfs("/")
        total = stat.f_blocks * stat.f_frsize
        used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
        result["disk_total_gb"] = round(total / (1024 ** 3), 2)
        result["disk_used_gb"] = round(used / (1024 ** 3), 2)
    except Exception:
        pass

    return result


def collect_docker_sizes() -> Dict:
    client = get_docker_client()
    if not client:
        return {"images_mb": 0, "containers_mb": 0, "volumes_mb": 0, "build_cache_mb": 0}

    try:
        disk_usage = client.df()
        images_size = sum(img.attrs.get("Size", 0) for img in disk_usage.get("Images", []))
        containers_size = sum(
            c.attrs.get("SizeRw", 0) + c.attrs.get("SizeRootFs", 0)
            for c in disk_usage.get("Containers", [])
        )
        volumes_size = sum(v.attrs.get("UsageData", {}).get("Size", 0) for v in disk_usage.get("Volumes", []))
        build_cache_size = disk_usage.get("BuildCache", 0)
        if isinstance(build_cache_size, list):
            build_cache_size = sum(
                bc.get("Size", 0) for bc in build_cache_size if isinstance(bc, dict)
            )

        return {
            "images_mb": round(images_size / (1024 * 1024), 2),
            "containers_mb": round(containers_size / (1024 * 1024), 2),
            "volumes_mb": round(volumes_size / (1024 * 1024), 2),
            "build_cache_mb": round(build_cache_size / (1024 * 1024), 2),
        }
    except Exception as e:
        logger.error(f"Error collecting docker sizes: {e}")
        return {"images_mb": 0, "containers_mb": 0, "volumes_mb": 0, "build_cache_mb": 0}


def get_running_containers() -> List[Dict]:
    client = get_docker_client()
    if not client:
        return []
    try:
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            labels = c.labels or {}
            result.append({
                "name": c.name,
                "image": str(c.image.tags[0]) if c.image.tags else str(c.image.id[:12]),
                "status": c.status,
                "slug": labels.get("sre.slug", ""),
            })
        return result
    except Exception:
        return []
