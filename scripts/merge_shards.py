"""Merge per-shard document xlsx files into a single consolidated workbook.

Scans `shards_dir` for `doc_data_shard_*.xlsx`, concatenates the main `Records`
sheet and the `Errors` sheet across all shards, de-duplicates by the
"Query ID" column, and writes the result to `output_path`.
"""

from __future__ import annotations

import argparse
import glob
import logging
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger("merge_shards")


def _copy_rows(source_sheet, target_sheet, seen_ids: set[str]) -> int:
    added = 0
    for row in source_sheet.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        qid = str(row[0])
        if qid in seen_ids:
            continue
        seen_ids.add(qid)
        target_sheet.append(list(row))
        added += 1
    return added


def merge(shards_dir: Path, output_path: Path, main_sheet: str = "Records", error_sheet: str = "Errors", pattern: str = "doc_data_shard_*.xlsx") -> None:
    shard_files = sorted(glob.glob(str(shards_dir / pattern)))
    if not shard_files:
        raise SystemExit(f"No shard files found in {shards_dir}")

    logger.info("Merging %d shard files into %s", len(shard_files), output_path)

    out_wb = openpyxl.Workbook()
    out_main = out_wb.active
    out_main.title = main_sheet
    out_errors = out_wb.create_sheet(error_sheet)

    main_seen: set[str] = set()
    error_seen: set[str] = set()
    header_written_main = False
    header_written_errors = False

    for path in shard_files:
        logger.info("Reading %s", path)
        wb = openpyxl.load_workbook(path, read_only=True)
        if main_sheet in wb.sheetnames:
            src = wb[main_sheet]
            if not header_written_main:
                headers = [c.value for c in next(src.iter_rows(max_row=1))]
                out_main.append(headers)
                for cell in out_main[1]:
                    cell.font = Font(bold=True)
                header_written_main = True
            added = _copy_rows(src, out_main, main_seen)
            logger.info("  %s: +%d records", main_sheet, added)
        if error_sheet in wb.sheetnames:
            src = wb[error_sheet]
            if not header_written_errors:
                headers = [c.value for c in next(src.iter_rows(max_row=1))]
                out_errors.append(headers)
                for cell in out_errors[1]:
                    cell.font = Font(bold=True)
                header_written_errors = True
            added = _copy_rows(src, out_errors, error_seen)
            logger.info("  %s: +%d records", error_sheet, added)
        wb.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_wb.save(output_path)
    logger.info("Wrote %s (%d records, %d errors)", output_path, len(main_seen), len(error_seen))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards-dir", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("doc_data.xlsx"))
    parser.add_argument("--pattern", default="doc_data_shard_*.xlsx")
    args = parser.parse_args()
    merge(args.shards_dir, args.output, pattern=args.pattern)
