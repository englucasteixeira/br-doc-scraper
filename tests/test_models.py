from src.doc_scraper.errors import ErrorCategory
from src.doc_scraper.models import ErrorRecord


def test_error_record_default_category_unknown():
    rec = ErrorRecord(query_id="PRJ0000011", error_message="boom")
    assert rec.category == ErrorCategory.UNKNOWN
    assert rec.to_row() == ["PRJ0000011", "boom", "UNKNOWN"]


def test_error_record_to_row_includes_category():
    rec = ErrorRecord(
        query_id="PRJ0000021",
        error_message="vencido",
        category=ErrorCategory.EXPIRED,
    )
    assert rec.to_row() == ["PRJ0000021", "vencido", "EXPIRED"]
