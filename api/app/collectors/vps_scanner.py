"""
VPS-wide scanner: host listening TCP ports + Nginx/Apache vhost hostnames.

Runs inside sre-agent-api with host paths mounted read-only (see docker-compose):
``/etc`` → ``/host-etc``, ``/proc`` → ``/host-proc``, ``/usr`` → ``/host-usr``.
"""

import logging
import os
import re
import socket
import subprocess
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("sre")

PROBE_HOST = os.getenv("PROBE_HOST", "host.docker.internal")

VPS_SCAN_ENABLED = os.getenv("VPS_SCAN_ENABLED", "true").lower() == "true"

HOST_PROC_NET_TCP = os.getenv("HOST_PROC_NET_TCP", "/host-proc/net/tcp")

_SKIP_HP_RAW = os.getenv(
    "AUTO_DISCOVER_SKIP_HOST_PORTS",
    "3306,5432,5433,6379,6380,27017,5672,9092,2181,8500,25,22,51820",
)
SKIP_HOST_PORTS = {
    int(x.strip())
    for x in _SKIP_HP_RAW.split(",")
    if x.strip().isdigit()
}

HTTP_PORTS = {
    80,
    443,
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
    8443,
    9443,
    10443,
    2083,
    2087,
}

NGINX_CONFIG_DIRS = [
    "/host-etc/nginx",
    "/host-etc/nginx/sites-enabled",
    "/host-etc/nginx/conf.d",
    "/host-usr/local/nginx/conf",
]
APACHE_CONFIG_DIRS = [
    "/host-etc/apache2",
    "/host-etc/apache2/sites-enabled",
    "/host-etc/httpd",
    "/host-etc/httpd/conf.d",
    "/host-etc/httpd/conf",
]

_RE_APACHE_SERVER = re.compile(r"^\s*Server(?:Name|Alias)\s+(\S+)", re.I | re.M)
_RE_NGINX_SERVER_NAME = re.compile(r"^\s*server_name\s+([^;]+);", re.I | re.M)
_RE_LISTEN = re.compile(r"^\s*listen\s+(?:\[?[^\]]*\]?:)?(\d+)", re.I | re.M)
_RE_VHOST_OPEN = re.compile(r"<VirtualHost\s+([^>]+)>", re.I)
_RE_VHOST_CLOSE = re.compile(r"</VirtualHost\s*>", re.I)


def _run_cmd(cmd: List[str], timeout: int = 10) -> Optional[str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout
        return None
    except Exception:
        return None


def _ipv4_from_hex(ip_hex: str) -> str:
    h = ip_hex.strip()
    if len(h) != 8:
        return ""
    try:
        return socket.inet_ntoa(bytes.fromhex(h)[::-1])
    except Exception:
        return ""


def _parse_listen_ports_from_proc(path: str) -> List[int]:
    out: List[int] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        local_addr, st = parts[1], parts[3]
        if st != "0A":
            continue
        if ":" not in local_addr:
            continue
        ip_hex, port_hex = local_addr.rsplit(":", 1)
        try:
            port = int(port_hex, 16)
        except ValueError:
            continue
        ip = _ipv4_from_hex(ip_hex)
        if ip in ("127.0.0.1", ""):
            continue
        if port in SKIP_HOST_PORTS:
            continue
        out.append(port)
    return out


def scan_listening_ports() -> List[Dict]:
    if not VPS_SCAN_ENABLED:
        return []

    proc_ports: List[int] = []
    if os.path.isfile(HOST_PROC_NET_TCP):
        proc_ports = _parse_listen_ports_from_proc(HOST_PROC_NET_TCP)

    if proc_ports:
        seen: Set[int] = set()
        rows: List[Dict] = []
        for p in sorted(proc_ports):
            if p not in seen:
                seen.add(p)
                rows.append({"port": p, "process": "", "pid": ""})
        logger.info("VPS scan: %s listening TCP port(s) from %s", len(rows), HOST_PROC_NET_TCP)
        return rows

    ports: List[Dict] = []
    seen2: Set[int] = set()

    out = _run_cmd(["ss", "-tlnp"]) or _run_cmd(["netstat", "-tlnp"])
    if not out:
        logger.debug("VPS scan: no proc tcp file and ss/netstat unavailable")
        return []

    for line in out.splitlines():
        line = line.strip()
        if "LISTEN" not in line:
            continue
        parts = line.split()
        port = None
        for part in parts:
            if ":" in part:
                maybe = part.rsplit(":", 1)[-1]
                try:
                    port = int(maybe)
                except ValueError:
                    continue
                break
        if port is None or port in SKIP_HOST_PORTS or port in seen2:
            continue
        seen2.add(port)

        process = ""
        pid = ""
        for part in parts:
            if "pid=" in part:
                m = re.search(r"pid=(\d+)", part)
                if m:
                    pid = m.group(1)
                m2 = re.search(r"/(\S+)", part)
                if m2:
                    process = m2.group(1)
                break
            if re.match(r"\d+/", part):
                pid, process = part.split("/", 1)
                break

        ports.append({"port": port, "process": process, "pid": pid})

    ports.sort(key=lambda r: r["port"])
    logger.info("VPS scan: found %s TCP port(s) via ss/netstat (fallback)", len(ports))
    return ports


def _read_file(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def _find_files(dirs: List[str], extensions: Tuple[str, ...]) -> List[str]:
    files: List[str] = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            for entry in os.scandir(d):
                if entry.is_file() and any(entry.name.endswith(ext) for ext in extensions):
                    files.append(entry.path)
                elif entry.is_dir():
                    try:
                        for sub in os.scandir(entry.path):
                            if sub.is_file() and any(sub.name.endswith(ext) for ext in extensions):
                                files.append(sub.path)
                    except Exception:
                        pass
        except Exception:
            pass
    return files


def _expand_server_names(blob: str) -> List[str]:
    hosts: List[str] = []
    for token in blob.split():
        t = token.strip().rstrip(";")
        if not t or t == "_" or t.startswith("$") or "*" in t:
            continue
        hosts.append(t)
    return hosts


def _iter_nginx_server_blocks(content: str):
    """Yield inner text of each top-level ``server { ... }`` block (brace-balanced)."""
    idx = 0
    n = len(content)
    while idx < n:
        m = re.search(r"\bserver\s*\{", content[idx:], re.I)
        if not m:
            break
        brace_open = idx + m.end() - 1
        depth = 0
        i = brace_open
        while i < n:
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield content[brace_open + 1 : i]
                    idx = i + 1
                    break
            i += 1
        else:
            break


def nginx_hosts_by_port_from_content(content: str) -> Dict[int, List[str]]:
    """Parse Nginx config text: map listen port → server_name entries from each ``server`` block."""
    acc: Dict[int, List[str]] = defaultdict(list)
    for block in _iter_nginx_server_blocks(content):
        listens = [int(x) for x in _RE_LISTEN.findall(block)]
        if not listens:
            listens = [80]
        names: List[str] = []
        for match in _RE_NGINX_SERVER_NAME.findall(block):
            names.extend(_expand_server_names(match))
        if not names:
            continue
        for lp in listens:
            acc[lp].extend(names)
    return dict(acc)


def apache_hosts_by_port_from_content(content: str) -> Dict[int, List[str]]:
    """Parse Apache config text: map VirtualHost port → ServerName / ServerAlias."""
    acc: Dict[int, List[str]] = defaultdict(list)
    pos = 0
    cl = content.lower()
    while pos < len(content):
        m = _RE_VHOST_OPEN.search(content, pos)
        if not m:
            break
        inner_start = m.end()
        spec = m.group(1).strip()
        pm = re.search(r":(\d+)", spec)
        port = int(pm.group(1)) if pm else 80
        close_m = _RE_VHOST_CLOSE.search(content, inner_start)
        if not close_m:
            break
        body = content[inner_start : close_m.start()]
        names: List[str] = []
        for sn in _RE_APACHE_SERVER.findall(body):
            names.extend(_expand_server_names(sn))
        if names:
            acc[port].extend(names)
        pos = close_m.end()
    return dict(acc)


def parse_nginx_vhosts() -> Dict[int, List[str]]:
    merged: Dict[int, List[str]] = defaultdict(list)
    files = _find_files(NGINX_CONFIG_DIRS, (".conf",))
    for path in files:
        raw = _read_file(path)
        if not raw:
            continue
        for port, hosts in nginx_hosts_by_port_from_content(raw).items():
            merged[port].extend(hosts)
    return dict(merged)


def parse_apache_vhosts() -> Dict[int, List[str]]:
    merged: Dict[int, List[str]] = defaultdict(list)
    files = _find_files(APACHE_CONFIG_DIRS, (".conf",))
    for path in files:
        raw = _read_file(path)
        if not raw:
            continue
        for port, hosts in apache_hosts_by_port_from_content(raw).items():
            merged[port].extend(hosts)
    return dict(merged)


def discover_vps_deployments(docker_host_ports: Set[int]) -> List[Dict]:
    if not VPS_SCAN_ENABLED:
        return []

    nginx_vhosts = parse_nginx_vhosts()
    apache_vhosts = parse_apache_vhosts()
    all_vhosts: Dict[int, List[str]] = defaultdict(list)
    for src in (nginx_vhosts, apache_vhosts):
        for port, hosts in src.items():
            all_vhosts[port].extend(hosts)

    for port in list(all_vhosts.keys()):
        seen_h: Set[str] = set()
        uniq: List[str] = []
        for h in all_vhosts[port]:
            if h not in seen_h:
                seen_h.add(h)
                uniq.append(h)
        all_vhosts[port] = uniq

    listening = scan_listening_ports()
    listening_ports = {p["port"] for p in listening}
    process_map = {p["port"]: p.get("process", "") for p in listening}

    candidate_ports: Set[int] = set()
    for p in listening_ports:
        if p in HTTP_PORTS or p in all_vhosts:
            candidate_ports.add(p)

    candidate_ports -= docker_host_ports

    deployments: List[Dict] = []
    for port in sorted(candidate_ports):
        if port in SKIP_HOST_PORTS:
            continue

        scheme = "https" if port in (443, 8443, 9443, 10443, 2083, 2087) else "http"
        base_url = f"{scheme}://{PROBE_HOST}:{port}/"

        hostnames = all_vhosts.get(port, [])
        probe_host_header = hostnames[0] if hostnames else None

        proc = process_map.get(port, "")
        slug_base = proc or f"vps-port-{port}"
        safe_slug = slug_base.replace("/", "-").replace(" ", "_")[:48]
        dep_id = f"vps-{port}"
        slug = f"{safe_slug}-{port}"[:80]

        deployments.append(
            {
                "id": dep_id,
                "slug": slug,
                "environment": "vps-scan",
                "git_url": None,
                "health_url": base_url,
                "browser_url": base_url,
                "expected_selector": None,
                "tcp_checks": f"{PROBE_HOST}:{port}",
                "probe_host_header": probe_host_header,
                "container_id": None,
                "container_name": proc or None,
                "image": None,
                "status": "running",
                "vhost_names": hostnames,
                "source": "vps-scan",
            }
        )

    if deployments:
        logger.info("VPS scan: %s deployment(s) merged", len(deployments))
    return deployments
