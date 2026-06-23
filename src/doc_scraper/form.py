from __future__ import annotations

import io
import logging
import re
from typing import Optional

import pdfplumber
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from config import FormConfig, ScraperConfig
from .errors import ErrorCategory
from .models import DocRecord, ErrorRecord

logger = logging.getLogger(__name__)


_PDF_PATTERNS: dict[str, str] = {
    "field_validity":   r"VALIDADE[:\s]+(\d{2}/\d{2}/\d{4})",
    "field_address":    r"Endere[çc]o[:\s]+(.+?)(?=\s*Bairro|\n)",
    "field_district":   r"Bairro[:\s]+(.+?)(?=\s*Munic|\n)",
    "field_city":       r"Munic[íi]pio[:\s]+(.+?)(?=\s*Ocupa|\n)",
    "field_category":   r"Ocupa[çc][ãa]o[:\s]+(.+?)(?=\s*P[úu]blico|\n)",
    "field_audience":   r"P[úu]blico[:\s]+(.+?)(?=\s*Propriet|\n)",
    "field_owner":      r"Propriet[áa]rio[:\s]+(.+?)(?=\s*Respons|\n)",
    "field_operator":   r"Respons[áa]vel pelo Uso[:\s]+(.+?)(?=[ÁA]rea|\n\n|\Z)",
    "field_area":       r"[ÁA]rea[^\n:]*:\s*(\d[\d.,]*\s*m[²2]?)",
}


class CaptchaRejectedError(Exception):
    """Raised when the server explicitly rejects the submitted captcha."""


class _EarlyExit(Exception):
    """Signals that the server responded without opening a popup (captcha wrong or ID not found)."""


class FormSubmitter:
    """Fills the search form, submits it via AJAX, intercepts the result popup, and parses the PDF."""

    def __init__(
        self,
        config: ScraperConfig = ScraperConfig(),
        form_config: FormConfig = FormConfig(),
    ) -> None:
        self._config = config
        self._form = form_config

    def submit(self, page: Page, query_id: str, captcha_text: str) -> Optional[DocRecord | ErrorRecord]:
        try:
            self._fill_form(page, query_id, captcha_text)
            pdf_bytes = self._click_and_capture_pdf(page)

            if pdf_bytes is None:
                if self._is_captcha_error(page):
                    raise CaptchaRejectedError("Server rejected the captcha.")
                red_msg = self._extract_red_message(page)
                if red_msg:
                    category = classify_error(red_msg, self._form)
                    logger.info("[%s] Server message (%s): %s", query_id, category.value, red_msg)
                    return ErrorRecord(query_id=query_id, error_message=red_msg, category=category)
                return None

            return _parse_pdf_record(pdf_bytes, query_id)
        except CaptchaRejectedError:
            raise
        except PlaywrightTimeoutError:
            logger.warning("Timeout waiting for result for ID '%s'.", query_id)
            return None
        except Exception:
            logger.exception("Unexpected error submitting form for ID '%s'.", query_id)
            return None

    def _fill_form(self, page: Page, query_id: str, captcha_text: str) -> None:
        page.fill(self._form.id_field_selector, query_id)
        page.fill(self._form.captcha_field_selector, captcha_text)
        logger.debug("Form filled: id='%s', captcha='%s'.", query_id, captcha_text)

    def _click_and_capture_pdf(self, page: Page) -> Optional[bytes]:
        pdf_urls: list[str] = []
        pdf_marker = self._form.pdf_url_marker

        def on_request(request):
            if pdf_marker and pdf_marker in request.url:
                pdf_urls.append(request.url)

        page.context.on("request", on_request)
        try:
            with page.context.expect_page(timeout=30_000) as page_info:
                page.click(self._form.submit_button_selector)
                try:
                    page.wait_for_function(
                        f"() => document.querySelector('{self._form.red_message_selector}')"
                        f" || document.body.innerText.includes('{self._form.captcha_wrong_marker}')",
                        timeout=5_000,
                    )
                    raise _EarlyExit()
                except PlaywrightTimeoutError:
                    pass
            popup = page_info.value
            try:
                popup.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            popup.close()
        except _EarlyExit:
            pass
        except PlaywrightTimeoutError:
            pass
        finally:
            page.context.remove_listener("request", on_request)

        if not pdf_urls:
            return None

        response = page.context.request.get(pdf_urls[0])
        if response.status != 200:
            logger.warning("PDF download returned status %d for URL %s.", response.status, pdf_urls[0])
            return None
        return response.body()

    def _extract_red_message(self, page: Page) -> Optional[str]:
        try:
            loc = page.locator(self._form.red_message_selector)
            if loc.count() == 0:
                return None
            text = (loc.first.inner_text() or "").strip()
            return text or None
        except Exception:
            return None

    def _is_captcha_error(self, page: Page) -> bool:
        try:
            if self._form.captcha_wrong_marker in (page.locator("body").inner_text() or ""):
                return True
        except Exception:
            pass

        try:
            captcha = page.locator(self._form.captcha_field_selector)
            if captcha.count() > 0:
                classes = captcha.first.get_attribute("class") or ""
                if self._form.captcha_error_class in classes:
                    return True
        except Exception:
            pass

        try:
            if page.locator(f".{self._form.captcha_error_class}").count() > 0:
                return True
        except Exception:
            pass

        return False


def classify_error(message: str, form_cfg: FormConfig) -> ErrorCategory:
    haystack = (message or "").lower()
    checks = (
        (form_cfg.expired_marker, ErrorCategory.EXPIRED),
        (form_cfg.replaced_marker, ErrorCategory.REPLACED),
        (form_cfg.not_found_marker, ErrorCategory.NOT_FOUND_800501),
        (form_cfg.invalid_marker, ErrorCategory.INVALID_201705),
    )
    for marker, category in checks:
        if marker and marker.lower() in haystack:
            return category
    return ErrorCategory.UNKNOWN


def _parse_pdf_record(pdf_bytes: bytes, query_id: str) -> DocRecord:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(pg.extract_text() or "" for pg in pdf.pages)

    logger.debug("PDF text for %s:\n%s", query_id, text[:800])
    return _parse_text_record(text, query_id)


def _parse_text_record(text: str, query_id: str) -> DocRecord:
    f: dict[str, str] = {}
    for key, pattern in _PDF_PATTERNS.items():
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            f[key] = " ".join(m.group(1).split())

    owner = f.get("field_owner", "")
    identifier_match = re.match(r"([\d./-]+)\s*[-–]\s*(.+)", owner)

    return DocRecord(
        query_id=query_id,
        doc_number=query_id,
        entity_name=identifier_match.group(2).strip() if identifier_match else owner or None,
        entity_id=identifier_match.group(1).strip() if identifier_match else None,
        address=f.get("field_address"),
        district=f.get("field_district"),
        city=f.get("field_city"),
        validity=f.get("field_validity"),
        status="VALID",
        category=f.get("field_category"),
        audience=f.get("field_audience"),
        owner=f.get("field_owner"),
        operator=f.get("field_operator"),
        area=f.get("field_area"),
        raw_fields=f,
    )
