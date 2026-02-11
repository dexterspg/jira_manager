"""Navigate to a URL and report page load status."""

import logging

from automation.browser import BrowserSession
from automation.config import WEB_UI_BASE_URL, WEB_UI_HEADLESS, WEB_UI_TIMEOUT, validate_config

logger = logging.getLogger(__name__)


def navigate_to_url(
    url: str = "",
    headless: bool | None = None,
    timeout: int | None = None,
) -> str:
    """Navigate to a URL and return a status report.

    Args:
        url: The URL to navigate to. Falls back to WEB_UI_BASE_URL from .env.
        headless: Run browser headless. Defaults to WEB_UI_HEADLESS from .env.
        timeout: Navigation timeout in seconds. Defaults to WEB_UI_TIMEOUT from .env.

    Returns:
        A string describing the result (success with details, or error message).
    """
    target_url = url or WEB_UI_BASE_URL
    if not target_url:
        config_error = validate_config()
        if config_error:
            return config_error
        return "Error: No URL provided and WEB_UI_BASE_URL is not set."

    use_headless = headless if headless is not None else WEB_UI_HEADLESS
    use_timeout = timeout if timeout is not None else WEB_UI_TIMEOUT

    try:
        with BrowserSession(headless=use_headless, timeout=use_timeout) as session:
            logger.info("Navigating to %s", target_url)
            response = session.page.goto(target_url, wait_until="domcontentloaded")

            status_code = response.status if response else "unknown"
            page_title = session.page.title()
            final_url = session.page.url

            lines = [
                "Navigation successful.",
                f"  URL: {final_url}",
                f"  HTTP status: {status_code}",
                f"  Page title: {page_title or '(empty)'}",
            ]
            if final_url != target_url:
                lines.append(f"  Redirected from: {target_url}")

            result = "\n".join(lines)
            logger.info(result)
            return result

    except Exception as e:
        error_msg = f"Navigation failed: {type(e).__name__}: {e}"
        logger.error(error_msg)
        return error_msg


if __name__ == "__main__":
    # When run directly (python src/automation/navigate.py), the top-level
    # imports will have already resolved via the package. Use -m instead:
    #   cd src && python -m automation.navigate
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    print(navigate_to_url(headless=False))
