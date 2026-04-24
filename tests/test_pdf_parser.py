from src.doc_scraper.form import _parse_text_record
from src.doc_scraper.models import DocRecord


SAMPLE_TEXT = """
CERTIFICADO DE REGULARIDADE
VALIDADE: 31/12/2026
Endereço: Rua das Flores, 123
Bairro: Centro
Município: São Paulo
Ocupação: Comercial
Público: Geral
Proprietário: 12.345.678/0001-99 - Empresa Exemplo LTDA
Responsável pelo Uso: João da Silva
Área: 250 m2
"""


def test_parses_all_fields_from_well_formed_text():
    record = _parse_text_record(SAMPLE_TEXT, query_id="PRJ0000011")

    assert isinstance(record, DocRecord)
    assert record.query_id == "PRJ0000011"
    assert record.doc_number == "PRJ0000011"
    assert record.validity == "31/12/2026"
    assert record.address == "Rua das Flores, 123"
    assert record.district == "Centro"
    assert record.city == "São Paulo"
    assert record.category == "Comercial"
    assert record.audience == "Geral"
    assert record.owner == "12.345.678/0001-99 - Empresa Exemplo LTDA"
    assert record.operator == "João da Silva"
    assert record.status == "VALID"


def test_splits_owner_into_entity_id_and_name():
    record = _parse_text_record(SAMPLE_TEXT, query_id="PRJ0000011")

    assert record.entity_id == "12.345.678/0001-99"
    assert record.entity_name == "Empresa Exemplo LTDA"


def test_owner_without_identifier_falls_back_to_full_string():
    text = "Proprietário: Maria Souza\nResponsável pelo Uso: Maria Souza\n"
    record = _parse_text_record(text, query_id="PRJ0000021")

    assert record.entity_id is None
    assert record.entity_name == "Maria Souza"
    assert record.owner == "Maria Souza"


def test_missing_fields_remain_none_without_crashing():
    text = "VALIDADE: 01/01/2027\n"
    record = _parse_text_record(text, query_id="PRJ0000031")

    assert record.validity == "01/01/2027"
    assert record.address is None
    assert record.district is None
    assert record.city is None
    assert record.owner is None
    assert record.entity_name is None
    assert record.entity_id is None


def test_accepts_em_dash_as_separator_in_owner():
    text = "Proprietário: 99.888.777/0001-00 – Outra Empresa SA\nResponsável pelo Uso: Fulano\n"
    record = _parse_text_record(text, query_id="PRJ0000041")

    assert record.entity_id == "99.888.777/0001-00"
    assert record.entity_name == "Outra Empresa SA"


def test_collapses_whitespace_in_multiword_fields():
    text = "Endereço: Avenida  Paulista,   1000\nBairro: Bela Vista\n"
    record = _parse_text_record(text, query_id="PRJ0000051")

    assert record.address == "Avenida Paulista, 1000"
    assert record.district == "Bela Vista"
