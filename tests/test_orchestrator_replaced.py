from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.doc_scraper.errors import ErrorCategory
from src.doc_scraper.models import DocRecord, ErrorRecord
from src.doc_scraper.orchestrator import DocScraper, REPLACED_MAX_RETRIES, RunStats


@dataclass
class _ScraperCfg:
    id_prefix: str = "PRJ"
    id_zero_padding: int = 7


@dataclass
class _RateCfg:
    inter_id_delay_min: float = 0.0
    inter_id_delay_max: float = 0.0


def _make_scraper(scripted_results, record_replaced=False):
    scraper = DocScraper.__new__(DocScraper)
    scraper._config = _ScraperCfg()
    scraper._record_replaced = record_replaced
    scraper._query_ids = None
    scraper._current_id = None
    scraper.stats = RunStats()
    scraper._rate_config = _RateCfg()
    scraper._writer = MagicMock()
    scraper._submitter = MagicMock()
    scraper._browser_config = None
    scraper._captcha_config = None
    scraper._stop_at = None

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


def test_stats_count_each_outcome():
    rec = DocRecord(query_id="PRJ0000011")
    expired = ErrorRecord(query_id="PRJ0000021", error_message="vencido", category=ErrorCategory.EXPIRED)
    missing = ErrorRecord(query_id="PRJ0000031", error_message="(800501)", category=ErrorCategory.NOT_FOUND_800501)
    scraper = _make_scraper([rec, expired, missing, None])
    for qid in ("PRJ0000011", "PRJ0000021", "PRJ0000031", "PRJ0000041"):
        scraper._process_id(None, None, qid)
    assert (scraper.stats.records, scraper.stats.errors, scraper.stats.not_found) == (1, 1, 1)
    assert scraper.stats.failed == ["PRJ0000041"]
    assert scraper.stats.existing == ["PRJ0000011", "PRJ0000021"]


def test_failure_after_replaced_marks_the_queried_id():
    replaced = ErrorRecord(query_id="PRJ0000011", error_message="substituído", category=ErrorCategory.REPLACED)
    scraper = _make_scraper([replaced, None])
    scraper._process_id(None, None, "PRJ0000011")
    assert scraper.stats.failed == ["PRJ0000011"]


def test_record_replaced_writes_original_then_follows_tail():
    replaced = ErrorRecord(query_id="PRJ0000011", error_message="substituído", category=ErrorCategory.REPLACED)
    found = DocRecord(query_id="PRJ0000012")
    scraper = _make_scraper([replaced, found], record_replaced=True)
    scraper._process_id(None, None, "PRJ0000011")
    scraper._writer.append_error.assert_called_once_with(replaced)
    scraper._writer.append.assert_called_once_with(found)


def test_explicit_query_ids_replace_the_range():
    scraper = _make_scraper([])
    scraper._query_ids = ["PRJ20250000012", "PRJ20240000031"]
    assert list(scraper._id_range()) == ["PRJ20250000012", "PRJ20240000031"]


def test_worker_crash_marks_current_id_failed():
    scraper = _make_scraper([])
    scraper._query_ids = ["PRJ0000011", "PRJ0000021"]

    def boom():
        scraper._current_id = "PRJ0000021"
        raise RuntimeError("browser died")

    scraper.run = boom
    scraper._run_guarded()
    assert scraper.stats.failed == ["PRJ0000021"]


def test_replaced_query_counts_as_existing_once():
    replaced = ErrorRecord(query_id="PRJ0000011", error_message="substituído", category=ErrorCategory.REPLACED)
    scraper = _make_scraper([replaced, DocRecord(query_id="PRJ0000012")])
    scraper._process_id(None, None, "PRJ0000011")
    assert scraper.stats.existing == ["PRJ0000011"]


def test_run_parallel_splits_query_ids_and_merges_stats(monkeypatch):
    import src.doc_scraper.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "SpreadsheetWriter", lambda config: MagicMock())
    monkeypatch.setattr(orchestrator.time, "sleep", lambda seconds: None)
    seen = []

    def fake_run(self):
        seen.append(list(self._id_range()))
        self.stats.records += len(self._query_ids)
        self.stats.existing.extend(self._query_ids)
        return self.stats

    monkeypatch.setattr(DocScraper, "run", fake_run)
    ids = [f"PRJ{n:07d}" for n in (11, 21, 31)]
    stats = DocScraper.run_parallel(num_workers=2, query_ids=ids, form_config=MagicMock())
    assert sorted(seen) == [ids[:2], ids[2:]]
    assert stats.records == 3 and sorted(stats.existing) == ids


def test_merge_keeps_pending_ids():
    total = RunStats()
    total.merge(RunStats(records=1, pending=["PRJ0000021"]))
    total.merge(RunStats(pending=["PRJ0000051"]))
    assert total.pending == ["PRJ0000021", "PRJ0000051"]


def _run_with_budget(monkeypatch, stop_at, clock):
    """Runs `run()` over IDs 11..51 with a fake browser and a scripted clock."""
    import src.doc_scraper.orchestrator as orchestrator

    scraper = _make_scraper([DocRecord(query_id=f"PRJ{n:07d}") for n in (11, 21, 31, 41, 51)])
    scraper._query_ids = [f"PRJ{n:07d}" for n in (11, 21, 31, 41, 51)]
    scraper._stop_at = stop_at
    scraper._writer.already_scraped_ids.return_value = {"PRJ0000011"}
    browser = MagicMock()
    browser.__enter__.return_value = browser
    monkeypatch.setattr(orchestrator, "BrowserManager", lambda _cfg: browser)
    monkeypatch.setattr(orchestrator, "CaptchaSolver", lambda _cfg: None)
    monkeypatch.setattr(orchestrator.time, "time", lambda: next(clock))
    processed = []
    scraper._process_id = lambda _b, _s, qid: processed.append(qid)
    return scraper, scraper.run(), processed


def test_time_budget_stops_before_the_next_id(monkeypatch):
    clock = iter([100.0, 100.0, 200.0])
    scraper, stats, processed = _run_with_budget(monkeypatch, stop_at=150.0, clock=clock)
    assert processed == ["PRJ0000021", "PRJ0000031"]
    assert stats.pending == ["PRJ0000041"]
    assert stats.existing == ["PRJ0000011"]


def test_without_budget_every_id_runs(monkeypatch):
    scraper, stats, processed = _run_with_budget(monkeypatch, stop_at=None, clock=iter([]))
    assert processed == ["PRJ0000021", "PRJ0000031", "PRJ0000041", "PRJ0000051"]
    assert stats.pending == []
