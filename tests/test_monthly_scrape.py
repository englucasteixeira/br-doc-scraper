import json
import sys
from datetime import date, datetime
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.monthly_scrape import (
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_UNREACHABLE,
    YearState,
    advance_done_through,
    exit_code,
    extend_year,
    group_by_prefix,
    health_check,
    load_state,
    save_state,
    select_revisions,
    years_to_extend,
)
from src.doc_scraper.orchestrator import RunStats


def _dense(low, high):
    def probe(tail):
        return low <= tail <= high and tail % 10 == 1

    return probe


def _write_workbook(path, records, errors=()):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Records"
    sheet.append(["Query ID", "Doc Number", "Entity Name", "Validity"])
    for doc, validity in records:
        sheet.append([doc, doc, "EMPRESA FICTICIA", validity])
    error_sheet = workbook.create_sheet("Errors")
    error_sheet.append(["Query ID", "Error", "Category"])
    for qid, category in errors:
        error_sheet.append([qid, "mensagem", category])
    workbook.save(path)


def test_state_seeded_from_ranges_as_fully_scraped(tmp_path):
    ranges = tmp_path / "year_ranges.json"
    ranges.write_text(
        json.dumps({"2024": [11, 296061], "2025": [31, 273901], "2019": None})
    )
    state = load_state(tmp_path / "state.json", ranges)
    assert state == {
        2024: YearState(11, 296061, 296061),
        2025: YearState(31, 273901, 273901),
    }


def test_state_round_trip(tmp_path):
    path = tmp_path / "sub" / "state.json"
    state = {2026: YearState(11, 2001, 1500)}
    save_state(path, state)
    assert load_state(path, tmp_path / "missing.json") == state


def test_years_to_extend_are_previous_and_current():
    assert years_to_extend(date(2026, 11, 1)) == [2025, 2026]


def test_extend_known_year_only_grows_high():
    current = YearState(low=31, high=2001, done_through=2001)
    assert extend_year(
        _dense(31, 3051), current, max_tail=10_000, gap_tolerance=2
    ) == YearState(31, 3051, 2001)


def test_extend_known_year_without_new_ids_keeps_range():
    current = YearState(low=31, high=2001, done_through=2001)
    assert (
        extend_year(_dense(31, 2001), current, max_tail=10_000, gap_tolerance=2)
        == current
    )


def test_new_year_is_discovered_and_nothing_done():
    assert extend_year(
        _dense(101, 5001), None, max_tail=10_000, gap_tolerance=2
    ) == YearState(101, 5001, 100)


def test_new_year_without_ids_returns_none():
    assert (
        extend_year(lambda tail: False, None, max_tail=1_000, gap_tolerance=2) is None
    )


def test_done_through_reaches_high_without_failures():
    year = YearState(low=11, high=5001, done_through=2001)
    assert advance_done_through(year, [], "PRJ2026").done_through == 5001


def test_done_through_stops_before_first_failure_of_the_year():
    year = YearState(low=11, high=5001, done_through=2001)
    failed = ["PRJ20260004001", "PRJ20260003001", "PRJ20250000011"]
    assert advance_done_through(year, failed, "PRJ2026").done_through == 3000


def test_done_through_never_goes_back():
    year = YearState(low=11, high=5001, done_through=2001)
    assert (
        advance_done_through(year, ["PRJ20260000011"], "PRJ2026").done_through == 2001
    )


def test_select_revisions_window_order_limit_and_settled(tmp_path):
    _write_workbook(
        tmp_path / "doc_data_2024.xlsx",
        [
            ("PRJ20240000011", "20/11/2026"),  # in window
            ("PRJ20240000021", "17/10/2026"),  # already expired
            ("PRJ20240000031", "01/02/2027"),  # beyond window
            ("PRJ20240000041", datetime(2026, 10, 30)),  # in window, cell typed as date
        ],
    )
    _write_workbook(
        tmp_path / "doc_data_rev_2026_10.xlsx",
        [("PRJ20240000011", "20/11/2026")],
        errors=[("PRJ20250000051", "EXPIRED")],
    )
    _write_workbook(
        tmp_path / "doc_data_2025.xlsx",
        [
            ("PRJ20250000051", "05/11/2026"),  # settled by the revision file
            ("PRJ20250000061", "18/10/2026"),  # today is in the window
        ],
    )
    today = date(2026, 10, 18)
    assert select_revisions(tmp_path, today, 60) == [
        "PRJ20250000061",
        "PRJ20240000041",
        "PRJ20240000011",
    ]
    assert select_revisions(tmp_path, today, 60, limit=1) == ["PRJ20250000061"]


def test_exit_codes():
    assert exit_code(RunStats(records=3), health_ok=True) == EXIT_OK
    assert exit_code(RunStats(records=3, failed=["X"]), health_ok=True) == EXIT_PARTIAL
    assert exit_code(RunStats(failed=["X", "Y"]), health_ok=True) == EXIT_UNREACHABLE
    assert exit_code(RunStats(), health_ok=False) == EXIT_UNREACHABLE
    assert exit_code(RunStats(), health_ok=True) == EXIT_OK


def test_health_check_probes_low_of_latest_year():
    calls = []

    def factory(prefix):
        def probe(tail):
            calls.append((prefix, tail))
            return None

        return probe

    state = {2024: YearState(11, 99, 99), 2025: YearState(31, 99, 99)}
    assert health_check(factory, state) is False
    assert calls == [("PRJ2025", 31)]


def test_revisions_grouped_by_year_prefix_in_order():
    docs = ["PRJ20240000011", "PRJ20200000021", "PRJ20240000031"]
    assert group_by_prefix(docs) == {
        "PRJ2024": ["PRJ20240000011", "PRJ20240000031"],
        "PRJ2020": ["PRJ20200000021"],
    }
