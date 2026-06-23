import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.find_year_ranges import _next_tail, find_range


def _dense_range(low: int, high: int):
    """All tails ending in 1 in [low, high] exist."""
    def probe(tail):
        return low <= tail <= high and tail % 10 == 1
    return probe


def test_next_tail_already_ends_in_1():
    assert _next_tail(11) == 11
    assert _next_tail(101) == 101


def test_next_tail_rounds_up_to_ending_in_1():
    assert _next_tail(2) == 11
    assert _next_tail(12) == 21
    assert _next_tail(100) == 101
    assert _next_tail(110) == 111


def test_full_2021_range_converges_to_known_upper_bound():
    probe = _dense_range(11, 300_481)
    assert find_range(probe, max_tail=1_000_000, gap_tolerance=5) == (11, 300_481)


def test_tiny_range():
    probe = _dense_range(11, 21)
    assert find_range(probe, max_tail=1_000, gap_tolerance=2) == (11, 21)


def test_single_existing_id():
    probe = _dense_range(11, 11)
    assert find_range(probe, max_tail=1_000, gap_tolerance=2) == (11, 11)


def test_lower_bound_not_11():
    probe = _dense_range(101, 5_001)
    assert find_range(probe, max_tail=100_000, gap_tolerance=5) == (101, 5_001)


def test_empty_range_returns_none():
    assert find_range(lambda t: False, max_tail=1_000, gap_tolerance=2) is None


def test_single_gap_in_middle_does_not_truncate():
    """One missing ID in an otherwise dense range must not be mistaken for end-of-range."""
    def probe(tail):
        if tail == 501:
            return False
        return 11 <= tail <= 1_001 and tail % 10 == 1
    assert find_range(probe, max_tail=10_000, gap_tolerance=2) == (11, 1_001)


def test_gap_larger_than_tolerance_truncates_at_first_island():
    """A gap wider than gap_tolerance*10 stops the search at the end of the first island."""
    def probe(tail):
        if 11 <= tail <= 501 and tail % 10 == 1:
            return True
        if 2_001 <= tail <= 3_001 and tail % 10 == 1:
            return True
        return False
    lower, upper = find_range(probe, max_tail=10_000, gap_tolerance=5)
    assert lower == 11
    assert upper == 501


def test_ambiguous_none_treated_as_exists():
    """None (failed probe) must not truncate the range — it counts as 'exists'."""
    def probe(tail):
        if 11 <= tail <= 31 and tail % 10 == 1:
            return True
        if tail == 41:
            return None
        return False
    lower, upper = find_range(probe, max_tail=1_000, gap_tolerance=2)
    assert lower == 11
    assert upper == 41


def test_range_extending_beyond_max_tail_is_clamped():
    probe = lambda t: t % 10 == 1
    lower, upper = find_range(probe, max_tail=1_001, gap_tolerance=2)
    assert lower == 11
    assert upper <= 1_001


def test_probe_call_count_is_reasonable_for_large_range():
    """Sanity: ~50 probes for a 300k range with gap_tolerance=5."""
    call_count = [0]

    def probe(tail):
        call_count[0] += 1
        return 11 <= tail <= 300_481 and tail % 10 == 1

    find_range(probe, max_tail=1_000_000, gap_tolerance=5)
    assert call_count[0] < 100, f"Too many probes: {call_count[0]}"
