#!/usr/bin/env python3
"""Удаление старых файлов чеков (cron: 0 4 * * *)."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RECEIPTS_DIR = Path(os.getenv("RECEIPTS_DIR", str(ROOT / "receipts")))
MAX_AGE_DAYS = int(os.getenv("RECEIPT_MAX_AGE_DAYS", "30"))
MIN_FREE_GB = float(os.getenv("RECEIPT_MIN_FREE_GB", "1.0"))


def main() -> int:
    if not RECEIPTS_DIR.is_dir():
        print(f"skip: {RECEIPTS_DIR} not found")
        return 0

    cutoff = time.time() - MAX_AGE_DAYS * 86400
    removed = 0
    for path in RECEIPTS_DIR.iterdir():
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError as e:
            print(f"warn: {path.name}: {e}")

    try:
        stat = os.statvfs(RECEIPTS_DIR)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        if free_gb < MIN_FREE_GB:
            print(f"WARNING: receipts disk low: {free_gb:.2f} GB free")
            return 1
    except OSError:
        pass

    print(f"removed {removed} receipt file(s) older than {MAX_AGE_DAYS}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
