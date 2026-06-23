from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.doc_scraper.errors import ErrorCategory
from src.doc_scraper.models import DocRecord, ErrorRecord
from src.doc_scraper.orchestrator import DocScraper, REPLACED_MAX_RETRIES


@dataclass
class _ScraperCfg:
    id_prefix: str = "PRJ"
    id_zero_padding: int = 7


@dataclass
class _RateCfg:
    inter_id_delay_min: float = 0.0
    inter_id_delay_max: float = 0.0


def _make_scraper(scripted_results):
    scraper = DocScraper.__new__(DocScraper)
    scraper._config = _ScraperCfg()
    scraper._rate_config = _RateCfg()
    scraper._writer = MagicMock()
    scraper._submitter = MagicMock()
    scraper._browser_config = None
    scraper._captcha_config = None

    results_iter = iter(scripted_results)

    def fake_scrape_one(_browser, _solver, query_id):
        result = next(results_iter)
        if hasattr(result, "query_id_override"):
            return result.record
        return result

    scraper.scrape_one = fake_scrape_one
    return scraper


def test_increment_tail_basic():
    scraper = _make_scraper([])
    assert scraper._increment_tail("PRJ0000011") == "PRJ0000012"
    assert scraper._increment_tail("PRJ0000019") == "PRJ0000020"


def test_increment_tail_bad_prefix_returns_none():
    scraper = _make_scraper([])
    assert scraper._increment_tail("XXX0000011") is None


def test_doc_record_written_and_no_retry():
    rec = DocRecord(query_id="PRJ0000011")
    scraper = _make_scraper([rec])
    scraper._process_id(None, None, "PRJ0000011")
    scraper._writer.append.assert_called_once_with(rec)
    scraper._writer.append_error.assert_not_called()


def test_expired_writes_error_and_stops():
    err = ErrorRecord(query_id="PRJ0000011", error_message="vencido", category=ErrorCategory.EXPIRED)
    scraper = _make_scraper([err])
    scraper._process_id(None, None, "PRJ0000011")
    scraper._writer.append_error.assert_called_once_with(err)
    scraper._writer.append.assert_not_called()


def test_not_found_does_not_write():
    err = ErrorRecord(query_id="PRJ0000011", error_message="(800501) ...", category=ErrorCategory.NOT_FOUND_800501)
    scraper = _make_scraper([err])
    scraper._process_id(None, None, "PRJ0000011")
    scraper._writer.append_error.assert_not_called()
    scraper._writer.append.assert_not_called()


def test_invalid_201705_writes_error():
    err = ErrorRecord(query_id="PRJ0000011", error_message="[201705] ...", category=ErrorCategory.INVALID_201705)
    scraper = _make_scraper([err])
    scraper._process_id(None, None, "PRJ0000011")
    scraper._writer.append_error.assert_called_once_with(err)


def test_replaced_then_doc_record_uses_incremented_id():
    replaced = ErrorRecord(query_id="PRJ0000011", error_message="substituído", category=ErrorCategory.REPLACED)
    found = DocRecord(query_id="PRJ0000013")
    scraper = _make_scraper([replaced, replaced, found])

    seen_ids = []
    real_scrape = scraper.scrape_one

    def tracked(browser, solver, qid):
        seen_ids.append(qid)
        return real_scrape(browser, solver, qid)

    scraper.scrape_one = tracked
    scraper._process_id(None, None, "PRJ0000011")

    assert seen_ids == ["PRJ0000011", "PRJ0000012", "PRJ0000013"]
    scraper._writer.append.assert_called_once_with(found)
    scraper._writer.append_error.assert_not_called()


def test_replaced_exhausted_writes_error_after_max_retries():
    replaced = ErrorRecord(query_id="PRJ0000011", error_message="substituído", category=ErrorCategory.REPLACED)
    scraper = _make_scraper([replaced] * (REPLACED_MAX_RETRIES + 1))

    seen_ids = []
    real_scrape = scraper.scrape_one

    def tracked(browser, solver, qid):
        seen_ids.append(qid)
        return real_scrape(browser, solver, qid)

    scraper.scrape_one = tracked
    scraper._process_id(None, None, "PRJ0000011")

    assert seen_ids == ["PRJ0000011", "PRJ0000012", "PRJ0000013", "PRJ0000014"]
    assert scraper._writer.append_error.call_count == 1
    exhausted = scraper._writer.append_error.call_args[0][0]
    assert exhausted.category == ErrorCategory.REPLACED
    assert "exhausted" in exhausted.error_message.lower()


def test_scrape_one_returns_none_writes_nothing():
    scraper = _make_scraper([None])
    scraper._process_id(None, None, "PRJ0000011")
    scraper._writer.append.assert_not_called()
    scraper._writer.append_error.assert_not_called()
