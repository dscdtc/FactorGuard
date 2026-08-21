"""Build a portable FactorGuard competition submission archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "FactorGuard_submission.zip"

TOP_LEVEL_FILES = {
    "app.py",
    "config.py",
    "README.md",
    "requirements.txt",
    "setup.bat",
}
SOURCE_DIRS = {"DOC", "engine", "models", "pages", "scripts", "tests", "ui", "utils"}
FACTOR_REPOSITORY_FILES = {
    ".gitattributes",
    ".gitignore",
    "factor_index.json",
    "LICENSE",
    "README.en.md",
    "README.md",
    "repo_summary.json",
    "SKILL.md",
    "validation_summary_real.json",
}
EXCLUDED_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "artifacts",
    "dist",
    "venv",
    ".venv",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".building", ".log", ".tmp"}
DATA_FILES = {
    ROOT / "data" / "factor_master.duckdb",
    ROOT / "data" / "snapshot" / "daily_basic.parquet",
    ROOT / "data" / "snapshot" / "daily_ohlcv.parquet",
    ROOT / "data" / "snapshot" / "stock_basic.parquet",
    ROOT / "data" / "snapshot" / "manifest.json",
}
EVIDENCE_FILES = {
    ROOT / "tests" / "artifacts" / "apptest_full_flow.txt",
    ROOT / "tests" / "artifacts" / "apptest_real_audit.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a portable FactorGuard competition ZIP."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _is_included_source(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if path.name.startswith("tmp_") or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if any(part in EXCLUDED_DIR_NAMES for part in relative.parts):
        return False
    return path.is_file()


def collect_files() -> list[Path]:
    files = {ROOT / name for name in TOP_LEVEL_FILES}
    for directory_name in SOURCE_DIRS:
        directory = ROOT / directory_name
        if directory.exists():
            files.update(path for path in directory.rglob("*") if _is_included_source(path))
    factors_dir = ROOT / "Factors"
    if factors_dir.exists():
        for repository in factors_dir.iterdir():
            if repository.is_dir():
                files.update(
                    path
                    for name in FACTOR_REPOSITORY_FILES
                    if (path := repository / name).is_file()
                )
    files.update(path for path in DATA_FILES | EVIDENCE_FILES if path.is_file())
    return sorted(path for path in files if path.is_file())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_archive(output: Path) -> tuple[int, int, str]:
    required = DATA_FILES - {ROOT / "data" / "factor_master.duckdb"}
    missing = sorted(str(path.relative_to(ROOT)) for path in required if not path.is_file())
    if missing:
        raise FileNotFoundError("提交包缺少正式快照文件: " + ", ".join(missing))

    files = collect_files()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = sum(path.stat().st_size for path in files)
    manifest_files = []

    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            archive.write(path, f"FactorGuard/{relative}")
            manifest_files.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        package_manifest = {
            "built_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "file_count": len(files),
            "uncompressed_bytes": total_bytes,
            "excluded": [
                "DataSource upstream repositories",
                "nested .git directories",
                "pytest caches and generated screenshots",
                "copied source CSVs and .building files",
                "Python bytecode and runtime logs",
            ],
            "files": manifest_files,
        }
        archive.writestr(
            "FactorGuard/PACKAGE_MANIFEST.json",
            json.dumps(package_manifest, ensure_ascii=False, indent=2),
        )

    archive_hash = sha256_file(output)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{archive_hash}  {output.name}\n", encoding="ascii"
    )
    return len(files), total_bytes, archive_hash


def main() -> None:
    args = parse_args()
    file_count, total_bytes, archive_hash = build_archive(args.output)
    print(f"提交包已生成: {args.output.resolve()}")
    print(f"文件数: {file_count} | 未压缩大小: {total_bytes / 1024 / 1024:.1f} MB")
    print(f"SHA-256: {archive_hash}")


if __name__ == "__main__":
    main()
