import httpx
import logging
import asyncio
from typing import Optional, Dict

logger = logging.getLogger("sre")

HTTP_TIMEOUT = 10.0


async def http_health_check(url: str) -> Dict:
    if not url:
        return {"success": False, "status_code": None, "response_time_ms": None, "error_message": "No health URL configured"}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            import time
            start = time.monotonic()
            response = await client.get(url)
            elapsed = (time.monotonic() - start) * 1000

            return {
                "success": 200 <= response.status_code < 400,
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
            "error_message": f"Connection refused: {str(e)[:100]}",
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": str(e)[:200],
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
