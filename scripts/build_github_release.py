"""Build clean GitHub source and snapshot release archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_OUTPUT = ROOT / "dist" / "FactorGuard_github_source.zip"
DEFAULT_SNAPSHOT_OUTPUT = (
    ROOT / "dist" / "FactorGuard_snapshot_20240927_20250926.zip"
)

TOP_LEVEL_FILES = {
    ".gitignore",
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
SOURCE_DATA_FILES = {
    ROOT / "data" / "snapshot" / "README.md",
    ROOT / "data" / "snapshot" / "manifest.json",
}
SNAPSHOT_FILES = SOURCE_DATA_FILES | {
    ROOT / "data" / "snapshot" / "daily_basic.parquet",
    ROOT / "data" / "snapshot" / "daily_ohlcv.parquet",
    ROOT / "data" / "snapshot" / "stock_basic.parquet",
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
EXCLUDED_SOURCE_SUFFIXES = {
    ".building",
    ".csv",
    ".duckdb",
    ".log",
    ".parquet",
    ".pyc",
    ".pyo",
    ".tmp",
}
SECRET_FILE_NAMES = {"secrets.toml", ".env"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create GitHub source and data release ZIP files."
    )
    parser.add_argument("--source-output", type=Path, default=DEFAULT_SOURCE_OUTPUT)
    parser.add_argument("--snapshot-output", type=Path, default=DEFAULT_SNAPSHOT_OUTPUT)
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Build only the source archive.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_included_source(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if path.name.startswith("tmp_"):
        return False
    if path.name in SECRET_FILE_NAMES or path.name.startswith(".env."):
        return False
    if path.suffix.lower() in EXCLUDED_SOURCE_SUFFIXES:
        return False
    if any(part in EXCLUDED_DIR_NAMES for part in relative.parts):
        return False
    return path.is_file()


def collect_source_files() -> list[Path]:
    files = {ROOT / name for name in TOP_LEVEL_FILES}
    for directory_name in SOURCE_DIRS:
        directory = ROOT / directory_name
        if directory.exists():
            files.update(
                path for path in directory.rglob("*") if _is_included_source(path)
            )

    factors_dir = ROOT / "Factors"
    if factors_dir.exists():
        for repository in factors_dir.iterdir():
            if repository.is_dir():
                files.update(
                    path
                    for name in FACTOR_REPOSITORY_FILES
                    if (path := repository / name).is_file()
                )

    files.update(path for path in SOURCE_DATA_FILES if path.is_file())
    collected = sorted(path for path in files if path.is_file())
    _validate_source_files(collected)
    return collected


def _validate_source_files(files: list[Path]) -> None:
    violations = []
    for path in files:
        relative = path.relative_to(ROOT)
        lower_parts = {part.lower() for part in relative.parts}
        if "datasource" in lower_parts or ".git" in lower_parts:
            violations.append(str(relative))
        if path.suffix.lower() in EXCLUDED_SOURCE_SUFFIXES:
            violations.append(str(relative))
        if path.name in SECRET_FILE_NAMES or path.name.startswith(".env."):
            violations.append(str(relative))
    if violations:
        raise ValueError("GitHub 源码包包含禁止文件：" + "、".join(sorted(set(violations))))


def _manifest_entry(path: Path) -> dict:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_hash_sidecar(output: Path) -> str:
    archive_hash = sha256_file(output)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{archive_hash}  {output.name}\n", encoding="ascii"
    )
    return archive_hash


def build_source_archive(output: Path) -> tuple[int, int, str]:
    files = collect_source_files()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = sum(path.stat().st_size for path in files)
    package_manifest = {
        "package_type": "github_source",
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "file_count": len(files),
        "uncompressed_bytes": total_bytes,
        "data_distribution": (
            "Parquet snapshots are distributed as a separate GitHub Release asset."
        ),
        "excluded": [
            "API keys, .env files, and Streamlit secrets",
            "DataSource upstream workspaces and nested .git directories",
            "Parquet, DuckDB, and raw CSV data",
            "test artifacts, caches, bytecode, logs, and temporary files",
        ],
        "files": [_manifest_entry(path) for path in files],
    }

    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            archive.write(path, f"FactorGuard/{relative}")
        archive.writestr(
            "FactorGuard/GITHUB_SOURCE_MANIFEST.json",
            json.dumps(package_manifest, ensure_ascii=False, indent=2),
        )

    return len(files), total_bytes, _write_hash_sidecar(output)


def build_snapshot_archive(output: Path) -> tuple[int, int, str]:
    missing = sorted(
        str(path.relative_to(ROOT)) for path in SNAPSHOT_FILES if not path.is_file()
    )
    if missing:
        raise FileNotFoundError("快照 Release 包缺少文件：" + "、".join(missing))

    files = sorted(SNAPSHOT_FILES)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = sum(path.stat().st_size for path in files)
    release_manifest = {
        "package_type": "factor_guard_snapshot",
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "files": [_manifest_entry(path) for path in files],
    }

    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            archive.write(path, f"FactorGuard/{relative}")
        archive.writestr(
            "FactorGuard/data/snapshot/RELEASE_MANIFEST.json",
            json.dumps(release_manifest, ensure_ascii=False, indent=2),
        )

    return len(files), total_bytes, _write_hash_sidecar(output)


def main() -> None:
    args = parse_args()
    source_count, source_bytes, source_hash = build_source_archive(args.source_output)
    print(f"GitHub 源码包: {args.source_output.resolve()}")
    print(
        f"源码文件数: {source_count} | 未压缩大小: {source_bytes / 1024 / 1024:.1f} MB"
    )
    print(f"源码 SHA-256: {source_hash}")

    if not args.source_only:
        snapshot_count, snapshot_bytes, snapshot_hash = build_snapshot_archive(
            args.snapshot_output
        )
        print(f"快照 Release 包: {args.snapshot_output.resolve()}")
        print(
            f"快照文件数: {snapshot_count} | "
            f"未压缩大小: {snapshot_bytes / 1024 / 1024:.1f} MB"
        )
        print(f"快照 SHA-256: {snapshot_hash}")


if __name__ == "__main__":
    main()
