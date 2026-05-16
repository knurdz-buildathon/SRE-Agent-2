import os
import platform
import time
from pathlib import Path
from typing import Dict, Optional, Tuple


HOST_PROC_ROOT = Path(os.getenv("HOST_PROC_ROOT", "/host-proc"))
HOST_ETC_ROOT = Path(os.getenv("HOST_ETC_ROOT", "/host-etc"))
HOST_ROOT = Path(os.getenv("HOST_ROOT", "/host-root"))
HOST_DISK_PATH = Path(os.getenv("HOST_DISK_PATH", str(HOST_ROOT)))
CPU_SAMPLE_SECONDS = float(os.getenv("HOST_CPU_SAMPLE_SECONDS", "0.1"))


def _existing_path(primary: Path, fallback: Path) -> Path:
    return primary if primary.exists() else fallback


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _parse_os_release(content: str) -> Optional[str]:
    values = {}
    for line in content.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values.get("PRETTY_NAME") or values.get("NAME")


def _cpu_times(proc_root: Path) -> Optional[Tuple[int, int]]:
    content = _read_text(proc_root / "stat")
    if not content:
        return None
    first = content.splitlines()[0].split()
    if not first or first[0] != "cpu":
        return None
    values = [int(v) for v in first[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def _cpu_percent(proc_root: Path) -> Optional[float]:
    first = _cpu_times(proc_root)
    if not first:
        return None
    time.sleep(max(0.01, CPU_SAMPLE_SECONDS))
    second = _cpu_times(proc_root)
    if not second:
        return None
    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0, (1 - (idle_delta / total_delta)) * 100)), 2)


def _cpu_count(proc_root: Path) -> int:
    content = _read_text(proc_root / "stat")
    if content:
        cpus = [
            line
            for line in content.splitlines()
            if line.startswith("cpu") and len(line) > 3 and line[3].isdigit()
        ]
        if cpus:
            return len(cpus)
    return os.cpu_count() or 0


def _load_average(proc_root: Path) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    content = _read_text(proc_root / "loadavg")
    if not content:
        try:
            return tuple(round(v, 2) for v in os.getloadavg())
        except (AttributeError, OSError):
            return None, None, None
    parts = content.split()
    try:
        return round(float(parts[0]), 2), round(float(parts[1]), 2), round(float(parts[2]), 2)
    except (IndexError, ValueError):
        return None, None, None


def _meminfo(proc_root: Path) -> Dict[str, float]:
    content = _read_text(proc_root / "meminfo")
    values = {}
    if content:
        for line in content.splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            parts = raw.split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) / 1024

    total = values.get("MemTotal", 0.0)
    available = values.get("MemAvailable", values.get("MemFree", 0.0))
    used = max(total - available, 0.0) if total else 0.0
    percent = (used / total) * 100 if total else 0.0
    return {
        "memory_total_mb": round(total, 2),
        "memory_available_mb": round(available, 2),
        "memory_used_mb": round(used, 2),
        "memory_percent": round(percent, 2),
    }


def _disk_usage(path: Path) -> Dict[str, float]:
    probe = path if path.exists() else Path("/")
    try:
        stat = os.statvfs(probe)
    except OSError:
        return {"disk_total_gb": 0.0, "disk_used_gb": 0.0, "disk_percent": 0.0}
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bavail * stat.f_frsize
    used = max(total - free, 0)
    percent = (used / total) * 100 if total else 0.0
    return {
        "disk_total_gb": round(total / (1024 ** 3), 2),
        "disk_used_gb": round(used / (1024 ** 3), 2),
        "disk_percent": round(percent, 2),
    }


def _uptime_seconds(proc_root: Path) -> Optional[float]:
    content = _read_text(proc_root / "uptime")
    if not content:
        return None
    try:
        return round(float(content.split()[0]), 2)
    except (IndexError, ValueError):
        return None


def _docker_version(docker_client_factory) -> str:
    if not docker_client_factory:
        return "unknown"
    client = docker_client_factory()
    if not client:
        return "unknown"
    try:
        return client.version().get("Version", "unknown")
    except Exception:
        return "unknown"


def collect_vps_metrics(docker_client_factory=None) -> Dict:
    proc_root = _existing_path(HOST_PROC_ROOT, Path("/proc"))
    etc_root = _existing_path(HOST_ETC_ROOT, Path("/etc"))
    disk_path = HOST_DISK_PATH if HOST_DISK_PATH.exists() else HOST_ROOT
    source = "host-mount" if HOST_PROC_ROOT.exists() else "container"

    os_name = None
    os_release = _read_text(etc_root / "os-release")
    if os_release:
        os_name = _parse_os_release(os_release)

    load1, load5, load15 = _load_average(proc_root)
    metrics = {
        "os_name": os_name or f"{platform.system()} {platform.release()}",
        "kernel": (_read_text(proc_root / "sys/kernel/osrelease") or platform.version()).strip(),
        "docker_version": _docker_version(docker_client_factory),
        "cpu_count": _cpu_count(proc_root),
        "cpu_percent": _cpu_percent(proc_root),
        "load_1m": load1,
        "load_5m": load5,
        "load_15m": load15,
        "uptime_seconds": _uptime_seconds(proc_root),
        "collection_source": source,
    }
    metrics.update(_meminfo(proc_root))
    metrics.update(_disk_usage(disk_path))
    return metrics
