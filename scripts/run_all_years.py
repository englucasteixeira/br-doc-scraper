"""Run the full scraper for every year listed in year_ranges.json.

Reads the JSON produced by `find_year_ranges.py`, then for each year:
- Sets prefix to PRJ{year}
- Sets id_start/id_end to the discovered range
- Writes output to artifacts/doc_data_{year}.xlsx (resume-safe; rerun skips
  already-scraped IDs via SpreadsheetWriter.already_scraped_ids)

Usage:
    python scripts/run_all_years.py
    python scripts/run_all_years.py --ranges year_ranges.json --output-dir artifacts --workers 2
    python scripts/run_all_years.py --years 2022,2023      # subset
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

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
from src.doc_scraper.orchestrator import DocScraper

logger = logging.getLogger("run_all_years")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranges", default="year_ranges.json")
    parser.add_argument("--output-dir", default="artifacts")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--years", default="",
                        help="Optional subset, e.g. '2022,2023'. Empty = all years in --ranges.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(threadName)s — %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("run_all_years.log", encoding="utf-8"),
        ],
    )

    ranges_path = Path(args.ranges)
    if not ranges_path.exists():
        logger.error("Ranges file %s not found. Run scripts/find_year_ranges.py first.", ranges_path)
        sys.exit(2)

    data = json.loads(ranges_path.read_text())
    requested = {int(y.strip()) for y in args.years.split(",") if y.strip()} if args.years else None

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_scraper = ScraperConfig()
    captcha_config = CaptchaConfig()
    form_config = FormConfig()
    validate_configs(base_scraper, captcha_config, form_config)

    for year_str, rng in sorted(data.items(), key=lambda kv: int(kv[0])):
        year = int(year_str)
        if requested is not None and year not in requested:
            continue
        if rng is None:
            logger.info("Skipping year %d (no IDs discovered).", year)
            continue
        low, high = rng

        prefix = f"PRJ{year}"
        output_path = output_dir / f"doc_data_{year}.xlsx"

        scraper_config = replace(base_scraper, id_prefix=prefix, id_start=low, id_end=high)
        storage_config = StorageConfig(output_path=str(output_path))

        logger.info("=== Year %d → IDs %d..%d → %s ===", year, low, high, output_path)
        DocScraper.run_parallel(
            num_workers=args.workers,
            scraper_config=scraper_config,
            browser_config=BrowserConfig(),
            captcha_config=captcha_config,
            storage_config=storage_config,
            rate_limit_config=RateLimitConfig(),
            form_config=form_config,
        )
        logger.info("Year %d complete: %s", year, output_path)

    logger.info("All years finished.")


if __name__ == "__main__":
    main()
