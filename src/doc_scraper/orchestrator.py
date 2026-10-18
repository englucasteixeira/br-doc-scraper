from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Iterator, Optional, Sequence

from config import BrowserConfig, CaptchaConfig, FormConfig, RateLimitConfig, ScraperConfig, StorageConfig
from .browser import BrowserManager
from .captcha import CaptchaSolver
from .errors import ErrorCategory
from .form import CaptchaRejectedError, FormSubmitter
from .models import DocRecord, ErrorRecord
from .storage import SpreadsheetWriter

REPLACED_MAX_RETRIES = 3

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    """Outcome counts of a run. `failed` holds query IDs that exhausted every attempt;
    `existing` holds query IDs known to exist (answered with a record or an error other
    than not-found, or already in the output and skipped)."""
    records: int = 0
    errors: int = 0
    not_found: int = 0
    failed: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)

    @property
    def answered(self) -> int:
        return self.records + self.errors + self.not_found

    def merge(self, other: "RunStats") -> None:
        self.records += other.records
        self.errors += other.errors
        self.not_found += other.not_found
        self.failed.extend(other.failed)
        self.existing.extend(other.existing)


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
        query_ids: Optional[Sequence[str]] = None,
        record_replaced: bool = False,
    ) -> None:
        """`query_ids` replaces the id_start..id_end range with an explicit list.
        `record_replaced` also writes REPLACED for the queried ID before following the
        tail (used when re-checking known documents)."""
        self._config = scraper_config
        self._query_ids = list(query_ids) if query_ids is not None else None
        self._record_replaced = record_replaced
        self._current_id: Optional[str] = None
        self.stats = RunStats()
        self._browser_config = browser_config
        self._captcha_config = captcha_config
        self._writer = _shared_writer if _shared_writer is not None else SpreadsheetWriter(storage_config)
        self._submitter = FormSubmitter(scraper_config, form_config)
        self._rate_config = rate_limit_config

    def run(self) -> RunStats:
        logger.info("Starting scraping run.")
        already_scraped = self._writer.already_scraped_ids()
        if already_scraped:
            logger.info("Resume: %d IDs already in output, will be skipped.", len(already_scraped))
        with BrowserManager(self._browser_config) as browser:
            solver = CaptchaSolver(self._captcha_config)
            for query_id in self._id_range():
                if query_id in already_scraped:
                    self.stats.existing.append(query_id)
                    continue
                self._current_id = query_id
                self._process_id(browser, solver, query_id)
        self._current_id = None
        logger.info("Scraping run complete.")
        return self.stats

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
        query_ids: Optional[Sequence[str]] = None,
        record_replaced: bool = False,
    ) -> RunStats:
        """Split the range (or `query_ids`) among workers and return the merged stats."""
        logger.info("Starting parallel scraping with %d workers.", num_workers)
        shared_writer = SpreadsheetWriter(storage_config)

        common = dict(
            browser_config=browser_config,
            captcha_config=captcha_config,
            storage_config=storage_config,
            rate_limit_config=rate_limit_config,
            form_config=form_config,
            _shared_writer=shared_writer,
            record_replaced=record_replaced,
        )
        workers: list[DocScraper] = []
        if query_ids is not None:
            ids = list(query_ids)
            chunk = -(-len(ids) // num_workers) if ids else 0
            for i in range(num_workers):
                part = ids[i * chunk:(i + 1) * chunk]
                if part:
                    workers.append(cls(scraper_config=scraper_config, query_ids=part, **common))
        else:
            total = scraper_config.id_end - scraper_config.id_start + 1
            chunk = total // num_workers
            for i in range(num_workers):
                start = scraper_config.id_start + i * chunk
                end = (start + chunk - 1) if i < num_workers - 1 else scraper_config.id_end
                workers.append(cls(
                    scraper_config=replace(scraper_config, id_start=start, id_end=end),
                    **common,
                ))

        threads = []
        for i, worker in enumerate(workers):
            if i > 0:
                time.sleep(random.uniform(3.0, 7.0))
            t = threading.Thread(target=worker._run_guarded, name=f"worker-{i}", daemon=True)
            t.start()
            threads.append(t)
            logger.info("Worker %d started (%s).", i, worker._describe_ids())

        for t in threads:
            t.join()

        stats = RunStats()
        for worker in workers:
            stats.merge(worker.stats)
        logger.info(
            "Parallel scraping complete: %d records, %d errors, %d not found, %d failed.",
            stats.records, stats.errors, stats.not_found, len(stats.failed),
        )
        return stats

    def _run_guarded(self) -> None:
        """Thread target: a crash marks the ID in progress (or the worker's first ID)
        as failed, so the caller retries from there instead of seeing a silent success."""
        try:
            self.run()
        except Exception:
            logger.exception("Worker crashed.")
            failed = self._current_id or next(self._id_range(), None)
            if failed is not None:
                self.stats.failed.append(failed)

    def _describe_ids(self) -> str:
        if self._query_ids is not None:
            return f"{len(self._query_ids)} listed IDs"
        return f"IDs {self._config.id_start}–{self._config.id_end}"

    def _process_id(self, browser: BrowserManager, solver: CaptchaSolver, query_id: str) -> None:
        current_id = query_id
        any_result = False
        for replaced_attempt in range(REPLACED_MAX_RETRIES + 1):
            record = self.scrape_one(browser, solver, current_id)
            if record is None:
                self.stats.failed.append(query_id)
                break
            any_result = True
            if current_id == query_id and not (
                isinstance(record, ErrorRecord) and record.category == ErrorCategory.NOT_FOUND_800501
            ):
                self.stats.existing.append(query_id)

            if isinstance(record, DocRecord):
                self._writer.append(record)
                self.stats.records += 1
                logger.info("[%s] Scraped successfully.", current_id)
                break

            if isinstance(record, ErrorRecord):
                if record.category == ErrorCategory.NOT_FOUND_800501:
                    logger.info("[%s] Not found (800501), skipping.", current_id)
                    self.stats.not_found += 1
                    break
                if record.category == ErrorCategory.REPLACED:
                    if self._record_replaced and replaced_attempt == 0:
                        self._writer.append_error(record)
                        self.stats.errors += 1
                    if replaced_attempt >= REPLACED_MAX_RETRIES:
                        exhausted = ErrorRecord(
                            query_id=current_id,
                            error_message="REPLACED retry exhausted: " + record.error_message,
                            category=ErrorCategory.REPLACED,
                        )
                        self._writer.append_error(exhausted)
                        self.stats.errors += 1
                        logger.info("[%s] REPLACED retry exhausted.", current_id)
                        break
                    next_id = self._increment_tail(current_id)
                    if next_id is None:
                        exhausted = ErrorRecord(
                            query_id=current_id,
                            error_message="REPLACED retry exhausted (tail overflow): " + record.error_message,
                            category=ErrorCategory.REPLACED,
                        )
                        self._writer.append_error(exhausted)
                        self.stats.errors += 1
                        logger.info("[%s] REPLACED tail overflow.", current_id)
                        break
                    logger.info("[%s] REPLACED — retrying with %s.", current_id, next_id)
                    current_id = next_id
                    continue
                self._writer.append_error(record)
                self.stats.errors += 1
                logger.info("[%s] Error recorded (%s): %s", current_id, record.category.value, record.error_message)
                break

        if any_result:
            time.sleep(random.uniform(self._rate_config.inter_id_delay_min, self._rate_config.inter_id_delay_max))

    def _increment_tail(self, query_id: str) -> Optional[str]:
        prefix = self._config.id_prefix
        padding = self._config.id_zero_padding
        if not query_id.startswith(prefix):
            return None
        tail = query_id[len(prefix):]
        try:
            num = int(tail)
        except ValueError:
            return None
        return f"{prefix}{str(num + 1).zfill(padding)}"

    def scrape_one(
        self,
        browser: BrowserManager,
        solver: CaptchaSolver,
        query_id: str,
    ) -> Optional[DocRecord | ErrorRecord]:
        """Run the captcha+submit pipeline with retries; return the parsed record without persisting."""
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

            page = None
            try:
                page = browser.new_page()
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

                if record is not None:
                    return record

                logger.warning("[%s] Form submission attempt %d/%d failed.", query_id, attempt, self._captcha_config.max_attempts)
                continue
            except Exception as exc:
                logger.warning(
                    "[%s] Unexpected error on attempt %d/%d (%s), retrying.",
                    query_id, attempt, self._captcha_config.max_attempts, exc,
                )
                continue
            finally:
                try:
                    page.close()
                except Exception:
                    pass

        logger.error("[%s] Exhausted all attempts, skipping.", query_id)
        return None

    def _id_range(self) -> Iterator[str]:
        if self._query_ids is not None:
            yield from self._query_ids
            return
        padding = self._config.id_zero_padding
        for num in range(self._config.id_start, self._config.id_end + 1):
            if num % 10 != 1:
                continue
            yield f"{self._config.id_prefix}{str(num).zfill(padding)}"
