import logging
import os
import sys
from dataclasses import replace

try:
    import secrets_local  # noqa: F401 — populates os.environ for local dev (gitignored)
except ImportError:
    pass

from config import ScraperConfig, StorageConfig
from src.doc_scraper import DocScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("doc_scraper.log", encoding="utf-8"),
    ],
)


def _scraper_config_from_env() -> ScraperConfig:
    base = ScraperConfig()
    return replace(
        base,
        id_start=int(os.environ.get("DOC_ID_START", base.id_start)),
        id_end=int(os.environ.get("DOC_ID_END", base.id_end)),
    )


def _storage_config_from_env() -> StorageConfig:
    base = StorageConfig()
    return replace(base, output_path=os.environ.get("DOC_OUTPUT_PATH", base.output_path))


if __name__ == "__main__":
    num_workers = int(os.environ.get("DOC_NUM_WORKERS", "2"))
    DocScraper.run_parallel(
        num_workers=num_workers,
        scraper_config=_scraper_config_from_env(),
        storage_config=_storage_config_from_env(),
    )
