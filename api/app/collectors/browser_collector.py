import logging
from typing import Optional, Dict

logger = logging.getLogger("sre")


def _describe_issue(status_code, page_blank, selector_found, expected_selector):
    if status_code and status_code >= 400:
        return f"HTTP {status_code}"
    if page_blank:
        return "Page appears blank (content < 50 chars)"
    if expected_selector and not selector_found:
        return f"Expected selector '{expected_selector}' not found"
    return "Unknown browser check failure"


async def browser_check(url: str, expected_selector: Optional[str] = None) -> Dict:
    if not url:
        return {
            "success": False,
            "status_code": None,
            "selector_found": False,
            "page_blank": True,
            "error_message": "No browser URL configured",
        }

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                response = await page.goto(url, wait_until="networkidle", timeout=15000)
                status_code = response.status if response else None

                content = await page.content()
                page_blank = len(content.strip()) < 50

                selector_found = True
                if expected_selector:
                    try:
                        element = await page.query_selector(expected_selector)
                        selector_found = element is not None
                    except Exception:
                        selector_found = False

                success = 200 <= (status_code or 0) < 400 and not page_blank
                if expected_selector:
                    success = success and selector_found

                error_message = None if success else _describe_issue(
                    status_code, page_blank, selector_found, expected_selector
                )

                return {
                    "success": success,
                    "status_code": status_code,
                    "selector_found": selector_found,
                    "page_blank": page_blank,
                    "error_message": error_message,
                }
            finally:
                await browser.close()

    except ImportError:
        return {
            "success": False,
            "status_code": None,
            "selector_found": False,
            "page_blank": True,
            "error_message": "Playwright not installed",
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": None,
            "selector_found": False,
            "page_blank": True,
            "error_message": str(e)[:200],
        }
