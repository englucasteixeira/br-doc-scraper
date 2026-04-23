"""Local portal-specific configuration.

Copy this file to `secrets_local.py` (gitignored) and fill in the values for
your target portal. The scraper code reads these values from environment
variables; importing this module populates `os.environ` for local development.

In CI (GitHub Actions), set the same variables via repository Secrets — this
file does not need to exist on the runner.
"""

from __future__ import annotations

import os

PORTAL = {
    # Full URL of the lookup form page.
    "DOC_TARGET_URL": "https://example.gov.br/path/to/lookup",

    # Document ID prefix and numeric range.
    "DOC_ID_PREFIX": "PRJ2021",
    "DOC_ID_START": "11",
    "DOC_ID_END": "300481",
    "DOC_ID_ZERO_PADDING": "7",

    # Form field selectors (CSS attribute selectors). Keep as-is from the portal.
    "DOC_ID_FIELD_SELECTOR": "[name='example:form:idField']",
    "DOC_CAPTCHA_FIELD_SELECTOR": "[name='example:form:captchaField']",
    "DOC_SUBMIT_BUTTON_SELECTOR": "[name='example:form:submitButton']",

    # Captcha image XPath.
    "DOC_CAPTCHA_IMG_XPATH": "//img[contains(@src,'/captchaEndpoint')]",

    # Server error signals.
    "DOC_CAPTCHA_WRONG_MARKER": "(20)",
    "DOC_CAPTCHA_ERROR_CLASS": "fieldError",
    "DOC_RED_MESSAGE_SELECTOR": "div.error-banner",

    # Network marker that identifies the result PDF URL.
    "DOC_PDF_URL_MARKER": "downloadEndpoint",
}

for _k, _v in PORTAL.items():
    os.environ.setdefault(_k, _v)
