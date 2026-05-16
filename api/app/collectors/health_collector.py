import asyncio
import logging
import os
import re
import ssl
import time
from typing import List, Optional, Dict, Set
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger("sre")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))
HTTP_VERIFY_SSL = os.getenv("HTTP_VERIFY_SSL", "true").lower() == "true"
HTTP_AVAILABILITY_MODE = os.getenv("HTTP_AVAILABILITY_MODE", "reachable").lower()
HTTP_PROBE_USER_AGENT = os.getenv(
    "HTTP_PROBE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36 SRE-Agent/1.0",
)
HTTP_TRY_HTTPS_FALLBACK = os.getenv("HTTP_TRY_HTTPS_FALLBACK", "true").lower() == "true"

PROBE_HOST = os.getenv("PROBE_HOST", "host.docker.internal").strip().lower()
_EXTRA_GATEWAY = os.getenv("HTTP_PROBE_GATEWAY_HOSTS", "").strip().lower()
GATEWAY_TCP_HOSTS: Set[str] = {PROBE_HOST}
for part in _EXTRA_GATEWAY.split(","):
    p = part.strip().lower()
    if p:
        GATEWAY_TCP_HOSTS.add(p)

# Connect to gateway (:host.docker.internal) but use TLS SNI + Host for the real vhost (curl --resolve)
HTTP_PROBE_GATEWAY_SNI = os.getenv("HTTP_PROBE_GATEWAY_SNI", "true").lower() == "true"

HTTP_PROBE_TRY_FALLBACK_PATHS = os.getenv("HTTP_PROBE_TRY_FALLBACK_PATHS", "true").lower() == "true"
_RAW_FALLBACK_PATHS = os.getenv(
    "HTTP_PROBE_FALLBACK_PATHS",
    "/health,/healthz,/ready,/status,/api/health,/live,/ping",
)
HTTP_PROBE_FALLBACK_PATHS: List[str] = [
    p.strip() for p in _RAW_FALLBACK_PATHS.split(",") if p.strip()
]


def _success_from_response(status_code: int) -> bool:
    if HTTP_AVAILABILITY_MODE == "reachable":
        return True
    return 200 <= status_code < 400


def _url_replace_path(base_url: str, path: str) -> str:
    p = urlparse(base_url)
    if not path.startswith("/"):
        path = "/" + path
    return urlunparse((p.scheme, p.netloc, path, "", "", ""))


def _expand_probe_candidates(primary_url: str) -> List[str]:
    if not primary_url:
        return []
    candidates = [primary_url]
    if not HTTP_PROBE_TRY_FALLBACK_PATHS or not HTTP_PROBE_FALLBACK_PATHS:
        return candidates

    parsed = urlparse(primary_url)
    norm = (parsed.path or "").rstrip("/") or "/"
    if norm != "/":
        return candidates

    seen = {primary_url}
    for fp in HTTP_PROBE_FALLBACK_PATHS:
        fp = fp.strip()
        if not fp.startswith("/"):
            fp = "/" + fp
        u = _url_replace_path(primary_url, fp)
        if u not in seen:
            seen.add(u)
            candidates.append(u)
    return candidates


def _is_gateway_tcp_hostname(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    return hostname.strip().lower() in GATEWAY_TCP_HOSTS


def _ssl_context_for_probe(sni_hostname: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not HTTP_VERIFY_SSL:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _parse_status_from_response_bytes(header_blob: bytes) -> Optional[int]:
    try:
        line = header_blob.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    except Exception:
        return None
    m = re.match(r"HTTP/\d\.\d\s+(\d{3})", line)
    if not m:
        return None
    return int(m.group(1))


async def _https_get_via_gateway_with_sni(
    url: str,
    tcp_hostname: str,
    tcp_port: int,
    sni_hostname: str,
) -> Dict:
    """TLS to gateway IP/host with SNI + Host set to the real HTTPS vhost."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    ssl_ctx = _ssl_context_for_probe(sni_hostname)
    start = time.monotonic()
    reader = None
    writer = None
    try:
        connect_timeout = min(HTTP_TIMEOUT, 60.0)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                tcp_hostname,
                tcp_port,
                ssl=ssl_ctx,
                server_hostname=sni_hostname,
                ssl_handshake_timeout=connect_timeout,
            ),
            timeout=connect_timeout,
        )
        req_lines = [
            f"GET {path} HTTP/1.1\r\n",
            f"Host: {sni_hostname}\r\n",
            f"User-Agent: {HTTP_PROBE_USER_AGENT}\r\n",
            "Accept: */*\r\n",
            "Connection: close\r\n",
            "\r\n",
        ]
        payload = "".join(req_lines).encode("ascii", errors="replace")
        writer.write(payload)
        await writer.drain()

        buf = b""
        read_deadline = min(HTTP_TIMEOUT, 60.0)
        while b"\r\n\r\n" not in buf and len(buf) < 262144:
            chunk = await asyncio.wait_for(reader.read(16384), timeout=read_deadline)
            if not chunk:
                break
            buf += chunk

        elapsed_ms = (time.monotonic() - start) * 1000
        status_code = _parse_status_from_response_bytes(buf)
        if status_code is None:
            return {
                "success": False,
                "status_code": None,
                "response_time_ms": round(elapsed_ms, 2),
                "error_message": "Invalid or empty HTTP response (gateway SNI probe)",
            }

        ok = _success_from_response(status_code)
        logger.debug(
            "SNI probe tcp=%s:%s sni=%s path=%s → %s (%.0fms) ok=%s",
            tcp_hostname,
            tcp_port,
            sni_hostname,
            path,
            status_code,
            elapsed_ms,
            ok,
        )
        return {
            "success": ok,
            "status_code": status_code,
            "response_time_ms": round(elapsed_ms, 2),
            "error_message": None,
        }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": HTTP_TIMEOUT * 1000,
            "error_message": "Timeout",
        }
    except ssl.SSLError as e:
        logger.debug("SNI probe SSLError: %s", str(e)[:120])
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": f"TLS error: {str(e)[:120]}",
        }
    except OSError as e:
        logger.debug("SNI probe OSError: %s", str(e)[:120])
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": f"Connection error: {str(e)[:120]}",
        }
    except Exception as e:
        logger.debug("SNI probe Exception: %s", str(e)[:120])
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": str(e)[:200],
        }
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def _http_get_once(url: str, host_header: Optional[str]) -> Dict:
    parsed = urlparse(url)

    # HTTPS via host-gateway: SNI must match the real vhost (Host header alone is insufficient).
    if (
        HTTP_PROBE_GATEWAY_SNI
        and parsed.scheme == "https"
        and host_header
        and str(host_header).strip()
        and _is_gateway_tcp_hostname(parsed.hostname)
    ):
        sni = str(host_header).strip()
        tcp_h = parsed.hostname or PROBE_HOST
        tcp_p = parsed.port or 443
        return await _https_get_via_gateway_with_sni(url, tcp_h, tcp_p, sni)

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
            logger.debug(
                "Probe %s Host=%s → %s %s (%.0fms) ok=%s",
                url,
                host_header,
                response.status_code,
                response.reason_phrase,
                elapsed,
                ok,
            )
            return {
                "success": ok,
                "status_code": response.status_code,
                "response_time_ms": round(elapsed, 2),
                "error_message": None,
            }
    except httpx.TimeoutException:
        logger.debug("Probe %s Host=%s → Timeout (%.0fs)", url, host_header, HTTP_TIMEOUT)
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": HTTP_TIMEOUT * 1000,
            "error_message": "Timeout",
        }
    except httpx.ConnectError as e:
        logger.debug("Probe %s Host=%s → ConnectError: %s", url, host_header, str(e)[:80])
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": f"Connection error: {str(e)[:120]}",
        }
    except httpx.HTTPError as e:
        logger.debug("Probe %s Host=%s → HTTPError: %s", url, host_header, str(e)[:80])
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": str(e)[:200],
        }
    except Exception as e:
        logger.debug("Probe %s Host=%s → Exception: %s", url, host_header, str(e)[:80])
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": str(e)[:200],
        }


async def _probe_one_url_with_https_fallback(url: str, host_header: Optional[str]) -> Dict:
    primary = await _http_get_once(url, host_header)
    if primary.get("success"):
        return primary

    if primary.get("status_code") is not None:
        if (
            HTTP_TRY_HTTPS_FALLBACK
            and url.startswith("http://")
            and HTTP_AVAILABILITY_MODE != "reachable"
        ):
            parsed = urlparse(url)
            port = parsed.port or 80
            if port in {443, 8443, 9443, 10443, 2083, 2087}:
                alt = "https://" + url[7:]
                second = await _http_get_once(alt, host_header)
                if second.get("success") or second.get("status_code") is not None:
                    return second
        return primary

    if HTTP_TRY_HTTPS_FALLBACK and url.startswith("http://"):
        em = (primary.get("error_message") or "").lower()
        tls_hints = ("tls", "ssl", "certificate", "handshake", "wrong version", "protocol", "eof occurred")
        conn_hints = ("connection", "refused", "reset", "broken pipe", "unexpected eof")

        if any(x in em for x in tls_hints) or any(x in em for x in conn_hints):
            alt = "https://" + url[7:]
            logger.debug("Retry health probe as HTTPS (connection error): %s", alt)
            second = await _http_get_once(alt, host_header)
            if second.get("success"):
                return second
            if second.get("status_code") is not None:
                return second

    return primary


async def http_health_check(url: str, host_header: Optional[str] = None) -> Dict:
    """
    GET health URL with optional Host header.

    For HTTPS URLs targeting ``PROBE_HOST`` with a probe Host/SNI name, uses TLS SNI to the vhost
    while connecting to the gateway (same idea as ``curl --resolve``).

    For URLs whose path is ``/``, tries ``HTTP_PROBE_FALLBACK_PATHS`` on the same origin.
    """
    if not url:
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": "No health URL configured",
        }

    last: Optional[Dict] = None
    for candidate in _expand_probe_candidates(url):
        last = await _probe_one_url_with_https_fallback(candidate, host_header)
        if last.get("success"):
            return last

    return last or {
        "success": False,
        "status_code": None,
        "response_time_ms": None,
        "error_message": "Probe failed",
    }


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
