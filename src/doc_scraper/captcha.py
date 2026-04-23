from __future__ import annotations

import io
import logging
from typing import Optional

import ddddocr
from PIL import Image
from playwright.sync_api import Page

from config import CaptchaConfig

logger = logging.getLogger(__name__)


class ImageProcessor:
    """Crops captcha image bytes in memory."""

    @staticmethod
    def crop_top(image_bytes: bytes, crop_ratio: float) -> bytes:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        new_height = int(height * crop_ratio)
        cropped = img.crop((0, 0, width, new_height))
        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        return buf.getvalue()


class CaptchaSolver:
    """Downloads the captcha image from a page and solves it via ddddocr, entirely in memory."""

    def __init__(self, config: CaptchaConfig = CaptchaConfig()) -> None:
        self._config = config
        self._ocr = ddddocr.DdddOcr(show_ad=False)
        self._processor = ImageProcessor()

    def solve(self, page: Page) -> Optional[str]:
        raw_bytes = self._capture(page)
        if raw_bytes is None:
            return None

        cropped_bytes = self._processor.crop_top(raw_bytes, self._config.crop_ratio)
        text = self._ocr.classification(cropped_bytes).strip()
        logger.info("OCR result: '%s'", text)

        if not self._is_valid(text):
            logger.warning("Captcha '%s' failed validation (expected %d chars).", text, self._config.expected_length)
            return None

        return text

    def _capture(self, page: Page) -> Optional[bytes]:
        try:
            page.wait_for_selector(self._config.captcha_xpath, timeout=self._config.expected_length * 2000)
            return page.locator(self._config.captcha_xpath).screenshot()
        except Exception:
            logger.exception("Failed to capture captcha image.")
            return None

    def _is_valid(self, text: str) -> bool:
        return len(text) == self._config.expected_length and text.isalnum()
