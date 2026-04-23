from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import replace
from typing import Iterator, Optional

from config import BrowserConfig, CaptchaConfig, FormConfig, RateLimitConfig, ScraperConfig, StorageConfig
from .browser import BrowserManager
from .captcha import CaptchaSolver
from .form import CaptchaRejectedError, FormSubmitter
from .models import ErrorRecord
from .storage import SpreadsheetWriter

logger = logging.getLogger(__name__)


class DocScraper:
    """
    Orchestrates the full scraping pipeline:
    navigate → solve captcha → submit form → parse result → persist.
    """

    def __init__(
        self,
        scraper_config: ScraperConfig = ScraperConfig(),
        browser_config: BrowserConfig = BrowserConfig(),
        captcha_config: CaptchaConfig = CaptchaConfig(),
        storage_config: StorageConfig = StorageConfig(),
        rate_limit_config: RateLimitConfig = RateLimitConfig(),
        form_config: FormConfig = FormConfig(),
        _shared_writer: Optional[SpreadsheetWriter] = None,
    ) -> None:
        self._config = scraper_config
        self._browser_config = browser_config
        self._captcha_config = captcha_config
        self._writer = _shared_writer if _shared_writer is not None else SpreadsheetWriter(storage_config)
        self._submitter = FormSubmitter(scraper_config, form_config)
        self._rate_config = rate_limit_config

    def run(self) -> None:
        logger.info("Starting scraping run.")
        already_scraped = self._writer.already_scraped_ids()
        if already_scraped:
            logger.info("Resume: %d IDs already in output, will be skipped.", len(already_scraped))
        with BrowserManager(self._browser_config) as browser:
            solver = CaptchaSolver(self._captcha_config)
            for query_id in self._id_range():
                if query_id in already_scraped:
                    continue
                self._process_id(browser, solver, query_id)
        logger.info("Scraping run complete.")

    @classmethod
    def run_parallel(
        cls,
        num_workers: int = 2,
        scraper_config: ScraperConfig = ScraperConfig(),
        browser_config: BrowserConfig = BrowserConfig(),
        captcha_config: CaptchaConfig = CaptchaConfig(),
        storage_config: StorageConfig = StorageConfig(),
        rate_limit_config: RateLimitConfig = RateLimitConfig(),
        form_config: FormConfig = FormConfig(),
    ) -> None:
        logger.info("Starting parallel scraping with %d workers.", num_workers)
        shared_writer = SpreadsheetWriter(storage_config)

        total = scraper_config.id_end - scraper_config.id_start + 1
        chunk = total // num_workers

        workers: list[DocScraper] = []
        for i in range(num_workers):
            start = scraper_config.id_start + i * chunk
            end = (start + chunk - 1) if i < num_workers - 1 else scraper_config.id_end
            workers.append(cls(
                scraper_config=replace(scraper_config, id_start=start, id_end=end),
                browser_config=browser_config,
                captcha_config=captcha_config,
                storage_config=storage_config,
                rate_limit_config=rate_limit_config,
                form_config=form_config,
                _shared_writer=shared_writer,
            ))

        threads = []
        for i, worker in enumerate(workers):
            if i > 0:
                time.sleep(random.uniform(3.0, 7.0))
            t = threading.Thread(target=worker.run, name=f"worker-{i}", daemon=True)
            t.start()
            threads.append(t)
            logger.info("Worker %d started (IDs %d–%d).", i, workers[i]._config.id_start, workers[i]._config.id_end)

        for t in threads:
            t.join()

        logger.info("Parallel scraping complete.")

    def _process_id(self, browser: BrowserManager, solver: CaptchaSolver, query_id: str) -> None:
        for attempt in range(1, self._captcha_config.max_attempts + 1):

            if attempt > 1:
                backoff = (
                    self._rate_config.retry_backoff_base
                    * (self._rate_config.retry_backoff_factor ** (attempt - 2))
                )
                jitter = random.uniform(
                    -self._rate_config.retry_backoff_jitter,
                    self._rate_config.retry_backoff_jitter,
                )
                time.sleep(max(0.0, backoff + jitter))

            page = browser.new_page()
            try:
                response = page.goto(self._config.target_url)
                if response is not None and response.status in (429, 503):
                    throttle = random.uniform(self._rate_config.throttle_min, self._rate_config.throttle_max)
                    logger.warning("[%s] HTTP %d — pausing %.0fs.", query_id, response.status, throttle)
                    time.sleep(throttle)
                    continue

                page.wait_for_load_state("networkidle")

                captcha_text = solver.solve(page)
                if captcha_text is None:
                    logger.warning("[%s] Captcha attempt %d/%d failed, retrying.", query_id, attempt, self._captcha_config.max_attempts)
                    continue

                try:
                    record = self._submitter.submit(page, query_id, captcha_text)
                except CaptchaRejectedError:
                    logger.warning(
                        "[%s] Captcha '%s' rejected by server (attempt %d/%d), retrying with new captcha.",
                        query_id, captcha_text, attempt, self._captcha_config.max_attempts,
                    )
                    continue
                finally:
                    page.close()

                if isinstance(record, ErrorRecord):
                    self._writer.append_error(record)
                    logger.info("[%s] Error recorded: %s", query_id, record.error_message)
                    time.sleep(random.uniform(self._rate_config.inter_id_delay_min, self._rate_config.inter_id_delay_max))
                    return
                if record is not None:
                    self._writer.append(record)
                    logger.info("[%s] Scraped successfully.", query_id)
                    time.sleep(random.uniform(self._rate_config.inter_id_delay_min, self._rate_config.inter_id_delay_max))
                    return

                logger.warning("[%s] Form submission attempt %d/%d failed.", query_id, attempt, self._captcha_config.max_attempts)
                continue
            finally:
                # Guard: close page if not already closed by the inner try/finally.
                try:
                    page.close()
                except Exception:
                    pass

        logger.error("[%s] Exhausted all attempts, skipping.", query_id)

    def _id_range(self) -> Iterator[str]:
        padding = self._config.id_zero_padding
        for num in range(self._config.id_start, self._config.id_end + 1):
            if num % 10 != 1:
                continue
            yield f"{self._config.id_prefix}{str(num).zfill(padding)}"
