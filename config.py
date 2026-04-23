from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw is not None else default


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    viewport_width: int = 1366
    viewport_height: int = 768
    locale: str = "pt-BR"
    timezone: str = "America/Sao_Paulo"
    args: tuple = field(default_factory=lambda: (
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ))


@dataclass(frozen=True)
class CaptchaConfig:
    crop_ratio: float = 0.55
    expected_length: int = 5
    max_attempts: int = 5
    captcha_xpath: str = field(default_factory=lambda: _env("DOC_CAPTCHA_IMG_XPATH", ""))


@dataclass(frozen=True)
class RateLimitConfig:
    inter_id_delay_min: float = 2.0
    inter_id_delay_max: float = 5.0
    retry_backoff_base: float = 1.5
    retry_backoff_factor: float = 2.0
    retry_backoff_jitter: float = 0.5
    throttle_min: float = 60.0
    throttle_max: float = 120.0


@dataclass(frozen=True)
class ScraperConfig:
    target_url: str = field(default_factory=lambda: _env("DOC_TARGET_URL", ""))
    id_prefix: str = field(default_factory=lambda: _env("DOC_ID_PREFIX", "PRJ"))
    id_start: int = field(default_factory=lambda: _env_int("DOC_ID_START", 1))
    id_end: int = field(default_factory=lambda: _env_int("DOC_ID_END", 1))
    id_zero_padding: int = field(default_factory=lambda: _env_int("DOC_ID_ZERO_PADDING", 7))
    page_load_timeout: int = 10_000


@dataclass(frozen=True)
class FormConfig:
    """Portal form selectors and server error signals — all env-driven."""
    id_field_selector: str = field(default_factory=lambda: _env("DOC_ID_FIELD_SELECTOR", ""))
    captcha_field_selector: str = field(default_factory=lambda: _env("DOC_CAPTCHA_FIELD_SELECTOR", ""))
    submit_button_selector: str = field(default_factory=lambda: _env("DOC_SUBMIT_BUTTON_SELECTOR", ""))
    captcha_wrong_marker: str = field(default_factory=lambda: _env("DOC_CAPTCHA_WRONG_MARKER", ""))
    captcha_error_class: str = field(default_factory=lambda: _env("DOC_CAPTCHA_ERROR_CLASS", ""))
    red_message_selector: str = field(default_factory=lambda: _env("DOC_RED_MESSAGE_SELECTOR", ""))
    pdf_url_marker: str = field(default_factory=lambda: _env("DOC_PDF_URL_MARKER", ""))


@dataclass(frozen=True)
class StorageConfig:
    output_path: str = "doc_data.xlsx"
    sheet_name: str = "Records"
    error_sheet_name: str = "Errors"
