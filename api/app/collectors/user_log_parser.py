import json
import logging
import os
import re
from typing import Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger("sre")

USER_LOG_DIR = os.getenv("USER_LOG_DIR", "/user-logs")

_METHODS = "GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS"
_COMMON_LOG_RE = re.compile(
    rf'(?P<remote>\S+)\s+\S+\s+\S+\s+\[[^\]]+\]\s+"(?P<method>{_METHODS})\s+(?P<path>\S+)\s+[^"]+"\s+(?P<status>\d{{3}})',
    re.I,
)
_KV_RE = re.compile(
    rf"\bmethod=(?P<method>{_METHODS})\b.*?\b(?:path|url|route|endpoint)=(?P<path>\S+).*?\b(?:status|status_code|statusCode|code)=(?P<status>\d{{3}})\b",
    re.I,
)
_KV_STATUS_FIRST_RE = re.compile(
    rf"\b(?:status|status_code|statusCode|code)=(?P<status>\d{{3}})\b.*?\bmethod=(?P<method>{_METHODS})\b.*?\b(?:path|url|route|endpoint)=(?P<path>\S+)",
    re.I,
)
_LOOSE_RE = re.compile(
    rf"\b(?P<method>{_METHODS})\s+(?P<path>/[^\s\"']*)\b.*?\b(?P<status>[45]\d{{2}})\b",
    re.I,
)
_ERROR_PATH_RE = re.compile(
    rf"\b(?P<method>{_METHODS})\s+(?P<path>/[^\s\"']*)\b",
    re.I,
)


def _first_value(data: Dict, *keys):
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _nested_get(data: Dict, *path):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _clean_path(value) -> str:
    raw = str(value or "").strip().strip('"').strip("'")
    if not raw:
        return "/unknown"
    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme or parsed.netloc else raw.split("?", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    return path[:500]


def _safe_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_log_entry(data: Dict, raw_line: str) -> Optional[Dict]:
    request = data.get("request") if isinstance(data.get("request"), dict) else {}
    response = data.get("response") if isinstance(data.get("response"), dict) else {}
    http = data.get("http") if isinstance(data.get("http"), dict) else {}

    method = (
        _first_value(data, "method", "httpMethod", "request_method")
        or _first_value(request, "method", "httpMethod")
        or _nested_get(http, "request", "method")
    )
    path = (
        _first_value(data, "path", "url", "route", "endpoint", "request_path")
        or _first_value(request, "path", "url", "route", "endpoint")
        or _nested_get(http, "target")
    )
    status = (
        _first_value(data, "status_code", "statusCode", "status", "code")
        or _first_value(response, "status_code", "statusCode", "status")
        or _nested_get(http, "response", "status_code")
    )

    if status is None:
        level = str(_first_value(data, "level", "severity", "log_level") or "").lower()
        if level in {"error", "fatal", "critical"} and (method or path):
            status = 500

    status_code = _safe_int(status)
    if not method or not path or status_code is None:
        return None

    return {
        "method": str(method).upper(),
        "path": _clean_path(path),
        "status_code": status_code,
        "duration_ms": _safe_int(_first_value(data, "duration_ms", "durationMs", "elapsed_ms")) or 0,
        "upstream": _first_value(data, "deployment", "service", "service_name", "app", "logger") or "",
        "remote_ip": _first_value(data, "remote_ip", "client_ip", "ip") or "",
        "logged_at": _first_value(data, "time", "timestamp", "ts", "datetime") or "",
        "raw_line": raw_line[:500],
        "source": "user_log",
    }


def parse_user_log_line(line: str) -> Optional[Dict]:
    """Parse app/user logs in JSON, common access log, or simple key-value formats."""
    raw = line.strip()
    if not raw:
        return None

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            parsed = _json_log_entry(data, raw)
            if parsed:
                return parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    for pattern in (_COMMON_LOG_RE, _KV_RE, _KV_STATUS_FIRST_RE, _LOOSE_RE):
        m = pattern.search(raw)
        if not m:
            continue
        return {
            "method": m.group("method").upper(),
            "path": _clean_path(m.group("path")),
            "status_code": int(m.group("status")),
            "duration_ms": 0,
            "upstream": "",
            "remote_ip": m.groupdict().get("remote") or "",
            "logged_at": "",
            "raw_line": raw[:500],
            "source": "user_log",
        }

    if re.search(r"\b(error|fatal|critical|exception|traceback)\b", raw, re.I):
        m = _ERROR_PATH_RE.search(raw)
        if m:
            return {
                "method": m.group("method").upper(),
                "path": _clean_path(m.group("path")),
                "status_code": 500,
                "duration_ms": 0,
                "upstream": "",
                "remote_ip": "",
                "logged_at": "",
                "raw_line": raw[:500],
                "source": "user_log",
            }

    return None
