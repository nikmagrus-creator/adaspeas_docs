#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create a consistent SQLite backup using sqlite3 backup API.")
    p.add_argument("--src", required=True, help="Path to source SQLite DB (e.g. /data/app.db)")
    p.add_argument("--dir", required=True, help="Directory to write backups into (e.g. /data/backups)")
    p.add_argument("--keep", type=int, default=7, help="How many latest backups to keep (default: 7)")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    src = Path(a.src)
    out_dir = Path(a.dir)
    keep = max(1, int(a.keep))

    if not src.exists():
        raise SystemExit(f"Source DB not found: {src}")

    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dst = out_dir / f"app_{ts}.sqlite"

    # Connect with WAL-awareness: checkpoint before backup when possible.
    src_conn = sqlite3.connect(str(src))
    try:
        try:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception:
            pass

        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    # Prune old backups.
    backups = sorted(out_dir.glob("app_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        try:
            old.unlink()
        except Exception:
            pass

    print(f"OK: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
