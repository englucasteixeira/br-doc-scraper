"""Discover the valid ID range for each year prefix (PRJ{year}).

Algorithm: exponential probing + binary search, with K-confirmation to
distinguish a real "end of range" from a single missing ID (gap).

A probe hits the real portal once via DocScraper.scrape_one. The probe is
classified as:
    True   = ID exists (DocRecord OR any error except NOT_FOUND_800501)
    False  = ID does not exist (NOT_FOUND_800501)
    None   = ambiguous (all captcha retries failed) — treated as True
             (conservative; never truncate the range due to scraping issues)

Usage:
    python scripts/find_year_ranges.py --years 2020-2025
    python scripts/find_year_ranges.py --years 2020,2022 --gap-tolerance 5 --max-tail 1000000

Writes incremental results to year_ranges.json (so a crash mid-run preserves
the years already found).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import secrets_local  # noqa: F401
except ImportError:
    pass

from config import (
    BrowserConfig,
    CaptchaConfig,
    FormConfig,
    RateLimitConfig,
    ScraperConfig,
    StorageConfig,
    validate_configs,
)
from src.doc_scraper.browser import BrowserManager
from src.doc_scraper.captcha import CaptchaSolver
from src.doc_scraper.errors import ErrorCategory
from src.doc_scraper.models import DocRecord, ErrorRecord
from src.doc_scraper.orchestrator import DocScraper

logger = logging.getLogger("find_year_ranges")

ProbeFn = Callable[[int], Optional[bool]]


def _next_tail(n: int) -> int:
    """Smallest integer >= n that ends in 1."""
    if n % 10 == 1:
        return n
    base = (n // 10) * 10
    candidate = base + 1
    return candidate if candidate >= n else candidate + 10


def _exists(probe: ProbeFn, tail: int) -> bool:
    return probe(tail) is not False


def _confirmed_missing(probe: ProbeFn, tail: int, gap_tolerance: int, max_tail: int) -> bool:
    """tail and the next gap_tolerance tails-ending-in-1 must all be missing."""
    for i in range(gap_tolerance + 1):
        t = tail + i * 10
        if t > max_tail:
            break
        if _exists(probe, t):
            return False
    return True


def find_range(
    probe: ProbeFn,
    *,
    max_tail: int = 1_000_000,
    gap_tolerance: int = 5,
    start_tail: int = 11,
) -> Optional[Tuple[int, int]]:
    """Discover (lower, upper) — both tails ending in 1 — that bracket the
    existing IDs for a single year. Returns None when nothing exists in
    [start_tail, max_tail]."""

    if _exists(probe, start_tail):
        lower = start_tail
    else:
        step = 10
        cur = _next_tail(start_tail + step)
        last_missing = start_tail
        while cur <= max_tail and not _exists(probe, cur):
            last_missing = cur
            step *= 2
            cur = _next_tail(cur + step)
        if cur > max_tail:
            return None
        low, high = last_missing, cur
        while high - low > 10:
            mid = _next_tail((low + high) // 2)
            if mid >= high:
                break
            if _exists(probe, mid):
                high = mid
            else:
                low = mid
        lower = high

    step = 10
    cur = _next_tail(lower + step)
    last_existing = lower
    transition: Optional[int] = None
    while cur <= max_tail:
        if _confirmed_missing(probe, cur, gap_tolerance, max_tail):
            transition = cur
            break
        last_existing = cur
        step *= 2
        cur = _next_tail(cur + step)
    if transition is None:
        return (lower, last_existing)

    low, high = last_existing, transition
    while high - low > 10:
        mid = _next_tail((low + high) // 2)
        if mid >= high:
            break
        if _confirmed_missing(probe, mid, gap_tolerance, max_tail):
            high = mid
        else:
            low = mid
    return (lower, low)


def _make_real_probe(scraper: DocScraper, browser, solver, prefix: str, padding: int) -> ProbeFn:
    def probe(tail: int) -> Optional[bool]:
        qid = f"{prefix}{str(tail).zfill(padding)}"
        record = scraper.scrape_one(browser, solver, qid)
        if record is None:
            logger.warning("[%s] ambiguous probe (None) — treating as exists.", qid)
            return None
        if isinstance(record, ErrorRecord) and record.category == ErrorCategory.NOT_FOUND_800501:
            logger.info("[%s] NOT_FOUND.", qid)
            return False
        kind = "DocRecord" if isinstance(record, DocRecord) else f"Error/{record.category.value}"
        logger.info("[%s] exists (%s).", qid, kind)
        return True
    return probe


def _parse_years(spec: str) -> list[int]:
    out: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(chunk))
    return sorted(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", default="2020-2025", help="e.g. '2020-2025' or '2020,2022,2024'")
    parser.add_argument("--gap-tolerance", type=int, default=5,
                        help="consecutive missing IDs (ending in 1) needed to confirm end-of-range")
    parser.add_argument("--max-tail", type=int, default=1_000_000)
    parser.add_argument("--output", default="year_ranges.json")
    parser.add_argument("--padding", type=int, default=7)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("find_year_ranges.log", encoding="utf-8"),
        ],
    )

    scraper_config = ScraperConfig()
    captcha_config = CaptchaConfig()
    form_config = FormConfig()
    validate_configs(scraper_config, captcha_config, form_config)

    years = _parse_years(args.years)
    logger.info("Discovering ranges for years: %s", years)

    results: dict[int, Optional[Tuple[int, int]]] = {}
    output_path = Path(args.output)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_xlsx = str(Path(tmpdir) / "probe.xlsx")
        scraper = DocScraper(
            scraper_config=scraper_config,
            browser_config=BrowserConfig(),
            captcha_config=captcha_config,
            storage_config=StorageConfig(output_path=tmp_xlsx),
            rate_limit_config=RateLimitConfig(),
            form_config=form_config,
        )

        with BrowserManager(BrowserConfig()) as browser:
            solver = CaptchaSolver(captcha_config)
            for year in years:
                prefix = f"PRJ{year}"
                logger.info("=== Year %d (prefix=%s) ===", year, prefix)
                probe = _make_real_probe(scraper, browser, solver, prefix, args.padding)
                rng = find_range(
                    probe,
                    max_tail=args.max_tail,
                    gap_tolerance=args.gap_tolerance,
                    start_tail=11,
                )
                results[year] = rng
                logger.info("Year %d range: %s", year, rng)
                output_path.write_text(json.dumps({str(k): v for k, v in results.items()}, indent=2))

    logger.info("Final results written to %s: %s", output_path, results)


if __name__ == "__main__":
    main()
