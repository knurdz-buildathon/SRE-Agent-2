import json
import re
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger("sre")

TRAEFIK_LOG_DIR = os.getenv("TRAEFIK_LOG_DIR", "/traefik-logs")


def parse_traefik_access_log(line: str) -> Optional[Dict]:
    """Parse a single Traefik access log line (JSON or common log format)."""
    line = line.strip()
    if not line:
        return None

    # Try JSON format first
    try:
        entry = json.loads(line)
        return {
            "method": entry.get("request_Method", entry.get("method", "")),
            "path": entry.get("request_Path", entry.get("path", "")),
            "status_code": int(entry.get("origin_Status", entry.get("status", 0))),
            "duration_ms": float(entry.get("duration", 0)) / 1_000_000 if isinstance(entry.get("duration"), (int, float)) and entry.get("duration", 0) > 1000 else float(entry.get("duration", 0)),
            "upstream": entry.get("service_name", entry.get("upstream", "")),
            "remote_ip": entry.get("request_X-Forwarded-For", entry.get("client_addr", "")).split(",")[0].strip(),
            "logged_at": entry.get("time", entry.get("started_at", "")),
            "raw_line": line[:500],
        }
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    # Try common log format: 127.0.0.1 - - [10/Oct/2000:13:55:36 +0000] "GET /api HTTP/1.1" 200 2326
    clf_pattern = r'(\S+) - - \[([^\]]+)\] "(\S+) (\S+) \S+" (\d+)'
    m = re.match(clf_pattern, line)
    if m:
        return {
            "method": m.group(3),
            "path": m.group(4),
            "status_code": int(m.group(5)),
            "duration_ms": 0,
            "upstream": "",
            "remote_ip": m.group(1),
            "logged_at": m.group(2),
            "raw_line": line[:500],
        }

    return None


def parse_traefik_log_file(filepath: str) -> List[Dict]:
    """Parse all lines in a Traefik access log file."""
    entries = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parsed = parse_traefik_access_log(line)
                if parsed:
                    entries.append(parsed)
    except Exception as e:
        logger.error(f"Error reading Traefik log {filepath}: {e}")
    return entries


def collect_traefik_logs() -> List[Dict]:
    """Collect and parse all Traefik access logs from the configured directory."""
    all_entries = []
    if not os.path.isdir(TRAEFIK_LOG_DIR):
        logger.debug(f"Traefik log directory not found: {TRAEFIK_LOG_DIR}")
        return all_entries

    for filename in os.listdir(TRAEFIK_LOG_DIR):
        filepath = os.path.join(TRAEFIK_LOG_DIR, filename)
        if os.path.isfile(filepath):
            entries = parse_traefik_log_file(filepath)
            all_entries.extend(entries)

    return all_entries


def categorize_user_errors(entries: List[Dict]) -> List[Dict]:
    """Group and categorize Traefik entries that represent user-facing errors."""
    from collections import defaultdict

    error_map = defaultdict(lambda: {"count": 0, "first_seen": None, "last_seen": None, "method": "", "upstream": ""})

    for entry in entries:
        code = entry.get("status_code", 0)
        if code < 400:
            continue

        path = entry.get("path", "/unknown")
        method = entry.get("method", "GET")
        key = (path, method, code)
        category = _error_category(code)

        bucket = error_map[key]
        bucket["count"] += 1
        bucket["method"] = method
        bucket["status_code"] = code
        bucket["path"] = path
        bucket["upstream"] = entry.get("upstream", "")
        bucket["error_category"] = category
        ts = entry.get("logged_at", "")
        if not bucket["first_seen"] or (ts and ts < bucket["first_seen"]):
            bucket["first_seen"] = ts
        if not bucket["last_seen"] or (ts and ts > bucket["last_seen"]):
            bucket["last_seen"] = ts

    return list(error_map.values())


def _error_category(code: int) -> str:
    if code == 400:
        return "bad_request"
    elif code == 401:
        return "unauthorized"
    elif code == 403:
        return "forbidden"
    elif code == 404:
        return "not_found"
    elif code == 429:
        return "rate_limited"
    elif 400 <= code < 500:
        return "client_error"
    elif code == 500:
        return "internal_error"
    elif code == 502:
        return "bad_gateway"
    elif code == 503:
        return "service_unavailable"
    elif code == 504:
        return "gateway_timeout"
    elif 500 <= code < 600:
        return "server_error"
    return "unknown"


def detect_traefik_incidents(entries: List[Dict], threshold: int = 5) -> List[Dict]:
    """Detect repeated errors from Traefik logs that should generate incidents."""
    categorized = categorize_user_errors(entries)
    incidents = []
    for err in categorized:
        if err["count"] >= threshold:
            code = err["status_code"]
            if 400 <= code < 500:
                severity = "warning"
                title = f"Repeated {code} for {err['path']}"
            elif 500 <= code < 600:
                severity = "critical"
                title = f"Server error {code} for {err['path']}"
            else:
                continue

            incidents.append({
                "title": title,
                "severity": severity,
                "error_category": err["error_category"],
                "trigger_type": "traefik_log",
                "count": err["count"],
                "path": err["path"],
                "suggested_fix": _traefik_fix(code, err["path"]),
            })
    return incidents


def _traefik_fix(code: int, path: str) -> str:
    if code == 404:
        return f"Repeated 404 from Traefik on {path}. Check router rule, frontend fallback route, or missing static asset."
    elif code == 502:
        return f"Repeated 502 Bad Gateway on {path}. Check upstream service health, network connectivity, and that the backend container is running."
    elif code == 503:
        return f"Repeated 503 Service Unavailable on {path}. The backend may be overloaded or not yet ready. Check container health and resource limits."
    elif code == 504:
        return f"Repeated 504 Gateway Timeout on {path}. The backend is not responding in time. Check for slow queries, deadlocks, or resource exhaustion."
    elif 400 <= code < 500:
        return f"Repeated {code} on {path}. Review request format, authentication configuration, and Traefik middleware settings."
    elif 500 <= code < 600:
        return f"Repeated {code} on {path}. Check upstream service logs for internal errors."
    return f"Review error {code} on {path}."
