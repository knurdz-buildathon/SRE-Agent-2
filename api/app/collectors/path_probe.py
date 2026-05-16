import logging
import os
from typing import Callable, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger("sre")

AUTO_DISCOVER_PROBE_HEALTH_PATHS = (
    os.getenv("AUTO_DISCOVER_PROBE_HEALTH_PATHS", "true").lower() == "true"
)
AUTO_DISCOVER_PATH_PROBE_TIMEOUT = float(os.getenv("AUTO_DISCOVER_PATH_PROBE_TIMEOUT", "2"))
HTTP_VERIFY_SSL = os.getenv("HTTP_VERIFY_SSL", "true").lower() == "true"

_RAW_HEALTH_PATHS = os.getenv(
    "AUTO_DISCOVER_HEALTH_PATHS",
    "/health,/healthz,/ready,/status,/api/health,/live,/ping,/",
)


def normalize_path(path: str) -> str:
    p = (path or "/").strip() or "/"
    return p if p.startswith("/") else f"/{p}"


def candidate_health_paths() -> List[str]:
    seen = set()
    out: List[str] = []
    for raw in _RAW_HEALTH_PATHS.split(","):
        path = normalize_path(raw)
        if path not in seen:
            seen.add(path)
            out.append(path)
    if "/" not in seen:
        out.append("/")
    return out


def replace_url_path(origin_url: str, path: str) -> str:
    parsed = urlparse(origin_url)
    return urlunparse((parsed.scheme, parsed.netloc, normalize_path(path), "", "", ""))


def _probe_status(url: str, host_header: Optional[str] = None) -> Optional[int]:
    headers = {"Accept": "*/*", "User-Agent": "SRE-Agent/auto-discovery"}
    if host_header:
        headers["Host"] = host_header
    try:
        with httpx.Client(
            timeout=AUTO_DISCOVER_PATH_PROBE_TIMEOUT,
            verify=HTTP_VERIFY_SSL,
            follow_redirects=True,
        ) as client:
            response = client.get(url, headers=headers)
            return response.status_code
    except Exception as e:
        logger.debug("Auto-discovery path probe failed for %s: %s", url, str(e)[:100])
        return None


def select_health_url(
    origin_url: str,
    explicit_path: Optional[str] = None,
    host_header: Optional[str] = None,
    probe_func: Optional[Callable[[str, Optional[str]], Optional[int]]] = None,
) -> str:
    """
    Pick a health URL for an auto-discovered HTTP origin.

    Explicit labels win. Otherwise, quickly probes common health paths and prefers
    a 2xx/3xx route over ``/`` so apps whose root returns 404 are not born down.
    """
    if explicit_path:
        return replace_url_path(origin_url, explicit_path)

    if not AUTO_DISCOVER_PROBE_HEALTH_PATHS:
        return replace_url_path(origin_url, "/")

    probe = probe_func or _probe_status
    first_reachable: Optional[str] = None

    for path in candidate_health_paths():
        url = replace_url_path(origin_url, path)
        status = probe(url, host_header)
        if status is None:
            continue
        if 200 <= status < 400:
            return url
        if first_reachable is None and status not in (404, 405):
            first_reachable = url

    return first_reachable or replace_url_path(origin_url, "/")
