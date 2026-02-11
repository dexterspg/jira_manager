"""Browser lifecycle management using Playwright sync API."""

import logging

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

logger = logging.getLogger(__name__)


class BrowserSession:
    """Manages a Playwright Chromium browser session.

    Supports context manager usage::

        with BrowserSession(headless=True) as session:
            page = session.page
            page.goto("https://example.com")
    """

    def __init__(self, headless: bool = True, timeout: int = 30):
        self.headless = headless
        self.timeout_ms = timeout * 1000
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserSession is not started. Use as a context manager.")
        return self._page

    def __enter__(self) -> "BrowserSession":
        logger.info("Launching Chromium (headless=%s, timeout=%dms)", self.headless, self.timeout_ms)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._page.set_default_navigation_timeout(self.timeout_ms)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._browser:
            logger.info("Closing browser")
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._page = None
        self._browser = None
        self._pw = None
