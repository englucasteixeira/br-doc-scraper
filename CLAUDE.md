# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Python web scraping project that queries a public document lookup portal, solves its image CAPTCHA, downloads result PDFs, and consolidates extracted fields into an Excel spreadsheet.

**Portal-specific configuration** (target URL, form field selectors, error markers, PDF URL signature) lives in `secrets_local.py` (gitignored) for local runs, or in environment variables / GitHub Secrets for CI. See `secrets_local.example.py` for the full list.

## Scraping Workflow

1. **Access site via Playwright** — navigate to `DOC_TARGET_URL` and locate the CAPTCHA image.
2. **Solve CAPTCHA with ddddocr** — crop to top 55%, run OCR, validate exactly 5 alphanumeric characters. Retry on invalid output.
3. **Submit form via AJAX** — fill the document-ID field and CAPTCHA field, click the submit button. The portal uses an ADF partial-page submit, not a standard HTTP POST.
4. **Detect result** — a blank popup window opens via `window.open`. The server fetches the result PDF in the background. Capture the PDF URL via `context.on('request')`, then re-download it using `context.request.get()` (shares session cookies).
5. **Parse PDF** — `pdfplumber` + regex to extract fields (validity, address, district, city, category, audience, owner, operator).
6. **Persist** — write one `DocRecord` row to Excel per successful scrape via `SpreadsheetWriter`.

## Server Response Signals (configured via env)

| Condition | Signal |
|---|---|
| Wrong captcha | Body contains `DOC_CAPTCHA_WRONG_MARKER` — no popup |
| ID not found / other server error | Red banner matching `DOC_RED_MESSAGE_SELECTOR` shown |
| Valid ID + correct captcha | Blank popup opens; server fetches a URL containing `DOC_PDF_URL_MARKER` |

The `DOC_CAPTCHA_ERROR_CLASS` CSS class is checked as fallback captcha-error signal.

## ID Range and Filtering Rule

- Range configured by `DOC_ID_START` / `DOC_ID_END` / `DOC_ID_PREFIX` / `DOC_ID_ZERO_PADDING`.
- **Only IDs whose numeric part ends in `1` have records.** The `_id_range` generator skips all others (`num % 10 != 1`), reducing total queries by ~90%.

## Architecture

Clean Code + OOP. Each class has a single responsibility. All configuration lives in `config.py`.

```
repo/
├── main.py                          # Entry point — logging + DocScraper.run_parallel()
├── config.py                        # Frozen dataclass configs (Browser, Captcha, Scraper, Storage, RateLimit, Form)
├── secrets_local.example.py         # Template for portal-specific config
├── secrets_local.py                 # Gitignored — local portal config
├── requirements.txt
└── src/
    └── doc_scraper/
        ├── __init__.py              # Exports DocScraper
        ├── orchestrator.py          # DocScraper — coordinates the pipeline; parallel workers
        ├── browser.py               # BrowserManager — Playwright lifecycle
        ├── captcha.py               # CaptchaSolver + ImageProcessor — ddddocr OCR pipeline
        ├── form.py                  # FormSubmitter — fills form, captures PDF URL, parses PDF
        ├── models.py                # DocRecord / ErrorRecord dataclasses
        └── storage.py               # SpreadsheetWriter — thread-safe incremental Excel writes
```

### Class responsibilities

| Class | File | Responsibility |
|---|---|---|
| `DocScraper` | orchestrator.py | Drives the ID range; coordinates all components; parallel workers |
| `BrowserManager` | browser.py | Opens/closes Playwright browser; stealth context setup |
| `CaptchaSolver` | captcha.py | Downloads captcha screenshot, crops, runs ddddocr, validates length |
| `ImageProcessor` | captcha.py | Crops captcha image before OCR |
| `FormSubmitter` | form.py | Fills form, captures PDF URL via request event, re-downloads PDF, parses with pdfplumber |
| `SpreadsheetWriter` | storage.py | Writes records to Excel incrementally (thread-safe) |
| `DocRecord` / `ErrorRecord` | models.py | Data model for a single query result / error |
| `CaptchaRejectedError` | form.py | Raised when the server rejects a submitted captcha |

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp secrets_local.example.py secrets_local.py   # then edit secrets_local.py with your portal's values
```

Dependencies:
- `playwright` — browser automation
- `ddddocr` — CAPTCHA OCR
- `pillow` — image cropping
- `openpyxl` — Excel output
- `pdfplumber` — PDF text extraction

## Running

```bash
# Full run (parallel, 2 workers)
python main.py

# Tight range for smoke tests
DOC_ID_START=11 DOC_ID_END=51 DOC_OUTPUT_PATH=smoke.xlsx python main.py
```

## CI

`.github/workflows/scrape.yml` runs a sharded matrix (`max-parallel: 2`, 60 shards) with resume-skip via `SpreadsheetWriter.already_scraped_ids()`. Portal-specific config is injected through GitHub repository Secrets (same keys as `secrets_local.example.py`).
