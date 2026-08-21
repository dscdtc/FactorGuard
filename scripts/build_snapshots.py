"""Explicit CLI for building FactorGuard Parquet snapshots."""

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DATA_LOCAL, DATA_SNAPSHOT
from engine.data_loader import build_snapshots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream local stock CSVs into FactorGuard Parquet snapshots."
    )
    parser.add_argument("--source-dir", type=Path, default=DATA_LOCAL)
    parser.add_argument("--snapshot-dir", type=Path, default=DATA_SNAPSHOT)
    parser.add_argument("--date-start", help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--date-end", help="Inclusive end date (YYYY-MM-DD).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_snapshots(
        source_dir=args.source_dir,
        snapshot_dir=args.snapshot_dir,
        date_start=args.date_start,
        date_end=args.date_end,
    )


if __name__ == "__main__":
    main()
