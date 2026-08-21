"""Release packaging contracts for GitHub source and snapshot assets."""

import json
from pathlib import Path

import pytest

from scripts.build_github_release import ROOT, collect_source_files, sha256_file


def test_github_source_collection_excludes_data_secrets_and_nested_repositories():
    relative_paths = {
        path.relative_to(ROOT).as_posix() for path in collect_source_files()
    }

    assert {
        ".gitignore",
        "app.py",
        "README.md",
        "engine/ai_analysis.py",
        "pages/08_报告与凭证.py",
        "tests/test_ai_analysis.py",
        "data/snapshot/README.md",
        "data/snapshot/manifest.json",
    } <= relative_paths

    forbidden_suffixes = {
        ".building",
        ".csv",
        ".duckdb",
        ".log",
        ".parquet",
        ".pyc",
        ".pyo",
        ".tmp",
    }
    for relative in relative_paths:
        path = Path(relative)
        lower_parts = {part.lower() for part in path.parts}
        assert "datasource" not in lower_parts
        assert ".git" not in lower_parts
        assert path.suffix.lower() not in forbidden_suffixes
        assert path.name != ".env"
        assert not path.name.startswith(".env.")
        assert path.name != "secrets.toml"


def test_formal_snapshot_files_match_manifest_hashes():
    manifest_path = ROOT / "data" / "snapshot" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["date_start"] == "2024-09-27"
    assert manifest["date_end"] == "2025-09-26"
    assert manifest["rows"] == 1_314_224
    assert manifest["stocks"] == 5_473

    missing = [
        item["name"]
        for item in manifest["files"]
        if not (manifest_path.parent / item["name"]).is_file()
    ]
    if missing:
        pytest.skip("GitHub 源码环境尚未安装正式快照：" + "、".join(missing))

    for item in manifest["files"]:
        snapshot_path = manifest_path.parent / item["name"]
        assert snapshot_path.stat().st_size == item["bytes"]
        assert sha256_file(snapshot_path) == item["sha256"]
