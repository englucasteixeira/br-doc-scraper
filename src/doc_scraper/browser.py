from __future__ import annotations

from types import TracebackType
from typing import Optional, Type

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from config import BrowserConfig

_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });
    Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US'] });
    window.chrome = { runtime: {} };
"""


class BrowserManager:
    """Manages the Playwright browser lifecycle as a context manager."""

    def __init__(self, config: BrowserConfig = BrowserConfig()) -> None:
        self._config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    def __enter__(self) -> "BrowserManager":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self._config.headless,
            args=list(self._config.args),
        )
        self._context = self._browser.new_context(
            user_agent=self._config.user_agent,
            viewport={"width": self._config.viewport_width, "height": self._config.viewport_height},
            locale=self._config.locale,
            timezone_id=self._config.timezone,
        )
        self._context.add_init_script(_STEALTH_SCRIPT)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def new_page(self) -> Page:
        if self._context is None:
            raise RuntimeError("BrowserManager must be used as a context manager.")
        return self._context.new_page()
