import httpx
import logging
import os
import asyncio
import time
from typing import Optional, Dict

logger = logging.getLogger("sre")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))
HTTP_VERIFY_SSL = os.getenv("HTTP_VERIFY_SSL", "true").lower() == "true"
# strict: 2xx–3xx only up | reachable: any HTTP status counts up (TLS/tcp responded — fixes Traefik 403/WAF)
HTTP_AVAILABILITY_MODE = os.getenv("HTTP_AVAILABILITY_MODE", "strict").lower()
HTTP_PROBE_USER_AGENT = os.getenv(
    "HTTP_PROBE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36 SRE-Agent/1.0",
)
HTTP_TRY_HTTPS_FALLBACK = os.getenv("HTTP_TRY_HTTPS_FALLBACK", "true").lower() == "true"


def _success_from_response(status_code: int) -> bool:
    if HTTP_AVAILABILITY_MODE == "reachable":
        return True
    return 200 <= status_code < 400


async def _http_get_once(url: str, host_header: Optional[str]) -> Dict:
    headers = {"User-Agent": HTTP_PROBE_USER_AGENT, "Accept": "*/*"}
    if host_header and str(host_header).strip():
        headers["Host"] = str(host_header).strip()

    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            verify=HTTP_VERIFY_SSL,
            follow_redirects=True,
        ) as client:
            start = time.monotonic()
            response = await client.get(url, headers=headers)
            elapsed = (time.monotonic() - start) * 1000
            ok = _success_from_response(response.status_code)
            return {
                "success": ok,
                "status_code": response.status_code,
                "response_time_ms": round(elapsed, 2),
                "error_message": None,
            }
    except httpx.TimeoutException:
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": HTTP_TIMEOUT * 1000,
            "error_message": "Timeout",
        }
    except httpx.ConnectError as e:
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": f"Connection error: {str(e)[:120]}",
        }
    except httpx.HTTPError as e:
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": str(e)[:200],
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": str(e)[:200],
        }


async def http_health_check(url: str, host_header: Optional[str] = None) -> Dict:
    """
    GET url with optional virtual-host Host header (needed when probing via host.docker.internal).

    If HTTP fails with no HTTP status (TLS / protocol mismatch), optionally retries as HTTPS on same socket.
    """
    if not url:
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": "No health URL configured",
        }

    primary = await _http_get_once(url, host_header)
    if primary.get("success"):
        return primary

    # Listener speaks HTTPS but URL says http://
    if (
        HTTP_TRY_HTTPS_FALLBACK
        and url.startswith("http://")
        and primary.get("status_code") is None
        and primary.get("error_message")
    ):
        em = primary["error_message"].lower()
        if any(x in em for x in ("tls", "ssl", "certificate", "handshake", "wrong version", "protocol")):
            alt = "https://" + url[7:]
            logger.debug("Retry health probe as HTTPS: %s", alt)
            second = await _http_get_once(alt, host_header)
            if second.get("success"):
                return second
            if second.get("status_code") is not None:
                return second

        # Plain connection refused / reset — try HTTPS anyway (common Traefik TLS-only edge)
        if HTTP_TRY_HTTPS_FALLBACK and ("connection" in em or "refused" in em or "reset" in em):
            alt = "https://" + url[7:]
            second = await _http_get_once(alt, host_header)
            if second.get("success"):
                return second
            if second.get("status_code") is not None:
                return second

    return primary


async def tcp_check(host: str, port: int) -> Dict:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
        return {"success": True, "error_message": None}
    except asyncio.TimeoutError:
        return {"success": False, "error_message": f"Timeout connecting to {host}:{port}"}
    except ConnectionRefusedError:
        return {"success": False, "error_message": f"Connection refused: {host}:{port}"}
    except Exception as e:
        return {"success": False, "error_message": str(e)[:200]}


async def run_tcp_checks(tcp_checks_str: str) -> list:
    if not tcp_checks_str:
        return []

    results = []
    for entry in tcp_checks_str.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        parts = entry.split(":")
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            continue
        result = await tcp_check(host, port)
        result["host"] = host
        result["port"] = port
        results.append(result)

    return results
