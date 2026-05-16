import docker
import logging
import os
import re
from typing import List, Dict, Optional, Tuple, Set

logger = logging.getLogger("sre")

DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
PROBE_HOST = os.getenv("PROBE_HOST", "host.docker.internal")
AUTO_DISCOVER_WEB = os.getenv("AUTO_DISCOVER_WEB", "true").lower() == "true"
SRE_AGENT_CONTAINER_NAME = os.getenv("SRE_AGENT_CONTAINER_NAME", "sre-agent-api")
AUTO_BROWSER_AUTO = os.getenv("AUTO_BROWSER_AUTO", "false").lower() == "true"

_AUTO_SKIP_RAW = os.getenv("AUTO_DISCOVER_SKIP_CONTAINERS", "sre-agent-api,sre-agent-web")
AUTO_DISCOVER_SKIP_CONTAINERS = {
    x.strip().lstrip("/") for x in _AUTO_SKIP_RAW.split(",") if x.strip()
}

_SKIP_HP_RAW = os.getenv(
    "AUTO_DISCOVER_SKIP_HOST_PORTS",
    "3306,5432,5433,6379,6380,27017,5672,9092,2181,8500",
)
AUTO_DISCOVER_SKIP_HOST_PORTS = {
    int(x.strip())
    for x in _SKIP_HP_RAW.split(",")
    if x.strip().isdigit()
}

HTTP_PRIORITY = (
    443,
    8443,
    9443,
    10443,
    80,
    8080,
    8000,
    8081,
    8888,
    3000,
    3001,
    4000,
    4200,
    5000,
    5001,
    9000,
    9080,
)

MAX_AUTO_PORTS = int(os.getenv("AUTO_DISCOVER_MAX_PORTS_PER_CONTAINER", "12"))
AUTO_DISCOVER_ORPHANS = os.getenv("AUTO_DISCOVER_ORPHANS", "false").lower() == "true"

_TRAEFIK_HOST_RES = [
    re.compile(r"Host\s*\(\s*`([^`]+)`", re.I),
    re.compile(r'Host\s*\(\s*"([^"]+)"', re.I),
    re.compile(r"Host\s*\(\s*'([^']+)'", re.I),
]


def extract_traefik_host(labels: Optional[dict]) -> Optional[str]:
    """Parse Host(`domain`) from Traefik Docker labels (v2/v3)."""
    if not labels:
        return None
    for key, val in labels.items():
        kl = key.lower()
        if "traefik" not in kl or "rule" not in kl:
            continue
        if not isinstance(val, str):
            continue
        for rx in _TRAEFIK_HOST_RES:
            m = rx.search(val)
            if m:
                host = m.group(1).strip()
                if host:
                    return host
    return None


def _probe_host_from_labels(labels: dict) -> Optional[str]:
    explicit = (labels.get("sre.probe_host") or labels.get("SRE.PROBE_HOST") or "").strip()
    if explicit:
        return explicit
    return extract_traefik_host(labels)


def _health_path_from_labels(labels: dict) -> str:
    """Auto-discovery probe path from ``sre.health_path`` (default ``/``)."""
    raw = (labels.get("sre.health_path") or labels.get("SRE.HEALTH_PATH") or "").strip()
    if not raw:
        return "/"
    return raw if raw.startswith("/") else f"/{raw}"


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


def _http_sort_key(port: int) -> int:
    try:
        return HTTP_PRIORITY.index(port)
    except ValueError:
        return len(HTTP_PRIORITY) + port


def extract_tcp_host_bindings(attrs: dict) -> List[Tuple[int, int]]:
    """Published TCP ports: (host_port, container_port)."""
    out: List[Tuple[int, int]] = []
    ports = attrs.get("NetworkSettings", {}).get("Ports") or {}
    for key, binds in ports.items():
        if "/" not in key:
            continue
        cport_str, proto = key.split("/", 1)
        if proto != "tcp":
            continue
        cport = int(cport_str)
        if not binds:
            continue
        for b in binds:
            hp = b.get("HostPort")
            if not hp:
                continue
            hip_raw = (b.get("HostIp") or "").strip()
            if hip_raw in ("127.0.0.1", "::1"):
                continue
            hp_int = int(hp)
            if hp_int not in AUTO_DISCOVER_SKIP_HOST_PORTS:
                out.append((hp_int, cport))
    if out:
        return out
    pb = attrs.get("HostConfig", {}).get("PortBindings") or {}
    for key, binds in pb.items():
        if "/" not in key:
            continue
        cport_str, proto = key.split("/", 1)
        if proto != "tcp":
            continue
        cport = int(cport_str)
        if not binds:
            continue
        for b in binds:
            hp = b.get("HostPort")
            if not hp:
                continue
            hp_int = int(hp)
            if hp_int not in AUTO_DISCOVER_SKIP_HOST_PORTS:
                out.append((hp_int, cport))
    return out


def extract_exposed_tcp_ports(attrs: dict) -> List[int]:
    exp = attrs.get("Config", {}).get("ExposedPorts") or {}
    ports = []
    for key in exp:
        if key.endswith("/tcp"):
            try:
                p = int(key.split("/")[0])
                if p not in AUTO_DISCOVER_SKIP_HOST_PORTS:
                    ports.append(p)
            except ValueError:
                continue
    return ports


def shared_network_dns_targets(agent_attrs: dict, target_attrs: dict) -> List[str]:
    agent_nets = agent_attrs.get("NetworkSettings", {}).get("Networks") or {}
    tgt_nets = target_attrs.get("NetworkSettings", {}).get("Networks") or {}
    shared = set(agent_nets.keys()) & set(tgt_nets.keys())
    names: List[str] = []
    for net in sorted(shared):
        ep = tgt_nets[net]
        for al in ep.get("Aliases") or []:
            if al:
                names.append(al)
        ip = ep.get("IPAddress")
        if ip:
            names.append(ip)
    base = (target_attrs.get("Name") or "").lstrip("/")
    if base:
        names.append(base)
    seen = set()
    uniq = []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _try_agent_attrs(client) -> dict:
    try:
        agent = client.containers.get(SRE_AGENT_CONTAINER_NAME)
        return agent.attrs
    except Exception:
        return {}


def discover_auto_deployments(client, labeled_container_ids: Set[str], containers: List) -> List[Dict]:
    """
    Scan Docker for published web ports (and internal ports on shared networks).
    Skips containers already covered by sre.monitor labels.
    """
    if not AUTO_DISCOVER_WEB:
        return []

    agent_attrs = _try_agent_attrs(client)
    auto: List[Dict] = []

    for container in containers:
        if container.id in labeled_container_ids:
            continue

        attrs = container.attrs
        lbls = attrs.get("Config", {}).get("Labels") or {}
        probe_h = _probe_host_from_labels(lbls)
        name = (attrs.get("Name") or "").lstrip("/")
        if name in AUTO_DISCOVER_SKIP_CONTAINERS:
            continue

        short = container.id[:12]
        safe_slug_base = name.replace("/", "-").replace(" ", "_")[:48] or "container"

        image_ref = attrs.get("Config", {}).get("Image") or ""
        image_short = image_ref.split("/")[-1][:80]

        state = attrs.get("State") or {}
        running = state.get("Running") or container.status == "running"

        bindings = extract_tcp_host_bindings(attrs)
        bindings.sort(key=lambda t: (_http_sort_key(t[0]), _http_sort_key(t[1]), t[0]))

        rows_emitted = 0

        for hp, cp in bindings[:MAX_AUTO_PORTS]:
            scheme = "https" if hp in (443, 8443, 9443, 10443) or cp in (443, 8443) else "http"
            hpath = _health_path_from_labels(lbls)
            base_url = f"{scheme}://{PROBE_HOST}:{hp}{hpath}"
            dep_id = f"auto-{short}-{hp}"
            slug = f"{safe_slug_base}-{hp}"[:80]

            tcp_parts = [f"{PROBE_HOST}:{h}" for h, _ in bindings[:MAX_AUTO_PORTS]]
            tcp_checks = ",".join(tcp_parts) if tcp_parts else None

            auto.append(
                {
                    "id": dep_id,
                    "slug": slug,
                    "environment": "auto-discovered",
                    "git_url": None,
                    "health_url": base_url,
                    "browser_url": base_url if AUTO_BROWSER_AUTO else None,
                    "expected_selector": None,
                    "tcp_checks": tcp_checks,
                    "probe_host_header": probe_h,
                    "container_id": container.id,
                    "container_name": name,
                    "image": image_short,
                    "status": "running" if running else "stopped",
                    "source": "docker",
                }
            )
            rows_emitted += 1

        if rows_emitted > 0:
            continue

        exposed = extract_exposed_tcp_ports(attrs)
        exposed.sort(key=_http_sort_key)

        if running and exposed and agent_attrs:
            targets = shared_network_dns_targets(agent_attrs, attrs)
            if targets:
                cp = exposed[0]
                scheme = "https" if cp in (443, 8443, 9443) else "http"
                host = targets[0]
                hpath = _health_path_from_labels(lbls)
                base_url = f"{scheme}://{host}:{cp}{hpath}"
                dep_id = f"auto-{short}-int-{cp}"
                slug = f"{safe_slug_base}-int-{cp}"[:80]
                tcp_checks = ",".join(f"{host}:{p}" for p in exposed[:MAX_AUTO_PORTS])
                auto.append(
                    {
                        "id": dep_id,
                        "slug": slug,
                        "environment": "auto-discovered",
                        "git_url": None,
                        "health_url": base_url,
                        "browser_url": base_url if AUTO_BROWSER_AUTO else None,
                        "expected_selector": None,
                        "tcp_checks": tcp_checks,
                        "probe_host_header": probe_h,
                        "container_id": container.id,
                        "container_name": name,
                        "image": image_short,
                        "status": "running",
                        "source": "docker",
                    }
                )
                continue

        # Optionally record containers with no HTTP port mapping (batch jobs, DB-only)
        if not AUTO_DISCOVER_ORPHANS:
            continue
        dep_id = f"auto-{short}-noxpose"
        slug = f"{safe_slug_base}-noxpose"[:80]
        auto.append(
            {
                "id": dep_id,
                "slug": slug,
                "environment": "auto-discovered",
                "git_url": None,
                "health_url": None,
                "browser_url": None,
                "expected_selector": None,
                "tcp_checks": None,
                "probe_host_header": probe_h,
                "container_id": container.id,
                "container_name": name,
                "image": image_short,
                "status": "running" if running else "stopped",
                "source": "docker",
            }
        )

    return auto


def discover_deployments() -> Tuple[List[Dict], bool]:
    """
    Deployments from (1) sre.monitor labels and (2) auto-scan of Docker publish mappings.

    Returns (deployments, docker_ok). docker_ok is False if the socket/API is
    unreachable — callers must not treat an empty list as "delete everything".
    """
    client = get_docker_client()
    if not client:
        logger.warning("Docker unavailable, skipping deployment discovery")
        return [], False

    try:
        containers = client.containers.list(all=True)
        labeled: List[Dict] = []
        labeled_ids: Set[str] = set()

        for container in containers:
            labels = container.labels or {}
            if not _monitor_label_enabled(labels):
                continue
            slug = labels.get("sre.slug") or labels.get("SRE.SLUG") or container.name.lstrip("/")
            probe_host = _probe_host_from_labels(labels)
            labeled.append(
                {
                    "id": slug,
                    "slug": slug,
                    "environment": labels.get("sre.environment")
                    or labels.get("SRE.ENVIRONMENT")
                    or "production",
                    "git_url": labels.get("sre.git_url") or labels.get("SRE.GIT_URL"),
                    "health_url": labels.get("sre.health_url") or labels.get("SRE.HEALTH_URL"),
                    "browser_url": labels.get("sre.browser_url") or labels.get("SRE.BROWSER_URL"),
                    "expected_selector": labels.get("sre.expected_selector")
                    or labels.get("SRE.EXPECTED_SELECTOR"),
                    "tcp_checks": labels.get("sre.tcp_checks") or labels.get("SRE.TCP_CHECKS"),
                    "probe_host_header": probe_host,
                    "container_id": container.id,
                    "container_name": container.name.lstrip("/"),
                    "image": str(container.image.tags[0])
                    if container.image.tags
                    else str(container.image.id[:12]),
                    "status": "running" if container.status == "running" else "stopped",
                    "source": "docker",
                }
            )
            labeled_ids.add(container.id)

        auto = discover_auto_deployments(client, labeled_ids, containers)
        merged = labeled + auto
        logger.info(
            "Docker discovery: %s labeled + %s auto-discovered = %s deployment(s)",
            len(labeled),
            len(auto),
            len(merged),
        )
        return merged, True
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
