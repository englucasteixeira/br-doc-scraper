import pytest

from src.doc_scraper.errors import ErrorCategory
from src.doc_scraper.form import classify_error


class _StubFormCfg:
    expired_marker = "vencido"
    replaced_marker = "substituído"
    not_found_marker = "(800501)"
    invalid_marker = "[201705]"


@pytest.mark.parametrize("message,expected", [
    ("AVCB está vencido desde 2020", ErrorCategory.EXPIRED),
    ("Este AVCB foi substituído por outro", ErrorCategory.REPLACED),
    ("(800501) Não foi encontrado um AVCB/CLCB VALIDO para número informado.", ErrorCategory.NOT_FOUND_800501),
    ("[201705] AVCB Inválido: dados inconsistentes", ErrorCategory.INVALID_201705),
    ("Erro desconhecido qualquer", ErrorCategory.UNKNOWN),
    ("", ErrorCategory.UNKNOWN),
])
def test_classify_error_categories(message, expected):
    assert classify_error(message, _StubFormCfg()) == expected


def test_classify_error_case_insensitive():
    assert classify_error("AVCB VENCIDO", _StubFormCfg()) == ErrorCategory.EXPIRED
    assert classify_error("Substituído POR NOVO", _StubFormCfg()) == ErrorCategory.REPLACED


def test_classify_error_cascade_order_prefers_expired_over_invalid():
    msg = "vencido [201705]"
    assert classify_error(msg, _StubFormCfg()) == ErrorCategory.EXPIRED


def test_classify_error_empty_marker_skipped():
    class CfgNoExpired:
        expired_marker = ""
        replaced_marker = "substituído"
        not_found_marker = "(800501)"
        invalid_marker = "[201705]"

    assert classify_error("anything vencido", CfgNoExpired()) == ErrorCategory.UNKNOWN
