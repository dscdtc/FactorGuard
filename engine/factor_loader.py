import json
import duckdb
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from config import FACTORS_DIR, DB_PATH
from models.factor_spec import FactorSpec

SKILL_REPOS = [
    "skill-quant-factor-directional-alpha",
    "skill-quant-factor-risk-pattern-alpha",
    "skill-quant-factor-volume-stat-alpha",
]

# ---- Demo 因子定义 ----
DEMO_FACTORS = [
    {
        "factor_id": "demo_future_leak",
        "name_cn": "Demo A: 未来函数因子",
        "category": "动量",
        "base": "return",
        "transform": "z",
        "params": {"window": -5},
        "description": "使用负向窗口（引入未来数据）的因子，用于演示时间正确性检测",
        "expected_direction": "higher",
        "source": "demo",
    },
    {
        "factor_id": "demo_duplicate_a",
        "name_cn": "Demo B: 20日收益因子",
        "category": "动量",
        "base": "return",
        "transform": "none",
        "params": {"window": 20},
        "description": "20日收益因子，与 demo_duplicate_b 高度相似",
        "expected_direction": "higher",
        "source": "demo",
    },
    {
        "factor_id": "demo_duplicate_b",
        "name_cn": "Demo B: 对数收益因子",
        "category": "动量",
        "base": "return",
        "transform": "log",
        "params": {"window": 20},
        "description": "20日对数收益因子，与 demo_duplicate_a 高度相似",
        "expected_direction": "higher",
        "source": "demo",
    },
    {
        "factor_id": "demo_small_cap",
        "name_cn": "Demo C: 小微盘暴露因子",
        "category": "规模",
        "base": "return",
        "transform": "z",
        "params": {"window": 5},
        "description": "原始RankIC较好的因子，但剔除微盘或中性化后显著衰减",
        "expected_direction": "higher",
        "source": "demo",
    },
    {
        "factor_id": "demo_buffett",
        "name_cn": "Demo D: 巴菲特质量代理因子",
        "category": "质量",
        "base": "return",
        "transform": "z",
        "params": {"window": 20},
        "description": "巴菲特质量框架的代理因子，ROE + 毛利率 + 负债率",
        "expected_direction": "higher",
        "source": "demo",
    },
]


def _get_conn() -> duckdb.DuckDBPyConnection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    return conn


def init_db() -> None:
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS factor_metadata (
            factor_id TEXT PRIMARY KEY,
            name_cn TEXT NOT NULL,
            category TEXT NOT NULL,
            expected_direction TEXT NOT NULL,
            source TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS precomputed_results (
            factor_id TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value DOUBLE,
            metric_meta TEXT,
            computed_at TEXT NOT NULL,
            PRIMARY KEY (factor_id, metric_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_runs (
            run_id TEXT PRIMARY KEY,
            factor_id TEXT NOT NULL,
            status TEXT NOT NULL,
            conclusion TEXT,
            evidence_hash TEXT,
            report_hash TEXT,
            run_params TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT,
            FOREIGN KEY (factor_id) REFERENCES factor_metadata(factor_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS suitability_cache (
            factor_id TEXT NOT NULL,
            dim1 TEXT NOT NULL,
            dim1_value TEXT NOT NULL,
            dim2 TEXT NOT NULL,
            dim2_value TEXT NOT NULL,
            rank_ic DOUBLE,
            sample_count INTEGER,
            evidence_level TEXT,
            PRIMARY KEY (factor_id, dim1, dim1_value, dim2, dim2_value)
        )
    """)
    conn.close()


def load_factor_index(skill_dir: Path) -> list[dict]:
    index_path = skill_dir / "factor_index.json"
    if not index_path.exists():
        return []
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_validation_summary(skill_dir: Path) -> dict:
    summary_path = skill_dir / "validation_summary_real.json"
    if not summary_path.exists():
        return {}
    with open(summary_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    out = {}
    for item in items:
        fid = item.get("factor_id")
        if fid:
            out[fid] = item
    return out


def _factor_index_to_spec(factor: dict) -> FactorSpec:
    return FactorSpec(
        factor_id=factor["factor_id"],
        name=factor.get("slug", factor.get("name_en", factor["factor_id"])),
        name_cn=factor["name_cn"],
        version="1.0.0",
        description=factor.get("rationale_cn", "") or "",
        formula=factor.get("formula_en"),
        formula_cn=factor.get("formula_cn"),
        expected_direction="higher",
        category=factor.get("category_cn", ""),
        base=factor.get("base", ""),
        transform=factor.get("transform", ""),
        params=factor.get("params", {}),
        inputs=[],
        frequency="1d",
        availability="after_close",
        availability_lag=1,
        min_window=20,
        universe_rule="historical_all_a",
        preprocess="mad3_zscore",
        neutralization=None,
        source="builtin",
        source_reference=factor.get("repository_url"),
        rationale_cn=factor.get("rationale_cn"),
    )


def load_all_factors(factors_root: Path = None) -> list[FactorSpec]:
    if factors_root is None:
        factors_root = FACTORS_DIR

    init_db()
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    all_specs: list[FactorSpec] = []

    # 加载内置因子
    for repo_name in SKILL_REPOS:
        skill_dir = factors_root / repo_name
        if not skill_dir.is_dir():
            continue

        index_items = load_factor_index(skill_dir)
        validation = load_validation_summary(skill_dir)

        for item in index_items:
            spec = _factor_index_to_spec(item)
            all_specs.append(spec)
            _insert_factor_metadata(conn, spec, now)

            val = validation.get(spec.factor_id, {})
            if val:
                _insert_precomputed_metrics(conn, spec.factor_id, val, now)

    # 加载 Demo 因子
    for demo in DEMO_FACTORS:
        spec = FactorSpec(
            factor_id=demo["factor_id"],
            name=demo["factor_id"],
            name_cn=demo["name_cn"],
            version="1.0.0",
            description=demo["description"],
            category=demo["category"],
            expected_direction=demo["expected_direction"],
            base=demo["base"],
            transform=demo["transform"],
            params=demo["params"],
            inputs=[],
            frequency="1d",
            availability="after_close",
            availability_lag=1,
            min_window=abs(demo["params"].get("window", 20)),
            universe_rule="historical_all_a",
            source=demo["source"],
        )
        all_specs.append(spec)
        _insert_factor_metadata(conn, spec, now)

    conn.close()
    return all_specs


def _insert_factor_metadata(conn, spec: FactorSpec, now: str) -> None:
    """Upsert factor metadata into DuckDB"""
    conn.execute(
        """
        INSERT OR REPLACE INTO factor_metadata
            (factor_id, name_cn, category, expected_direction, source, spec_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?,
            COALESCE((SELECT created_at FROM factor_metadata WHERE factor_id = ?), ?),
            ?)
        """,
        [
            spec.factor_id,
            spec.name_cn,
            spec.category,
            spec.expected_direction,
            spec.source,
            spec.model_dump_json(),
            spec.factor_id,
            now,
            now,
        ],
    )


def _insert_precomputed_metrics(conn, factor_id: str, val: dict, now: str) -> None:
    """将 validation_summary_real.json 中的预计算指标写入 DuckDB"""
    metrics = {
        "ic_mean_5d": val.get("ic_mean_5d"),
        "ic_std_5d": val.get("ic_std_5d"),
        "icir_5d": val.get("icir_5d"),
        "ic_observations": val.get("ic_observations"),
        "long_short_mean_5d": val.get("long_short_mean_5d"),
        "long_short_observations": val.get("long_short_observations"),
        "coverage": val.get("coverage"),
        "turnover": val.get("turnover_top_quintile"),
        "sample_rows": val.get("sample_rows"),
        "usable_rows": val.get("usable_rows"),
        "status": val.get("status"),
        "no_future_check": val.get("no_future_check"),
    }
    for mname, mvalue in metrics.items():
        if mvalue is not None:
            if isinstance(mvalue, bool):
                meta_val = json.dumps({"raw": mvalue})
                conn.execute(
                    "INSERT OR REPLACE INTO precomputed_results (factor_id, metric_name, metric_value, metric_meta, computed_at) VALUES (?, ?, NULL, ?, ?)",
                    [factor_id, mname, meta_val, now],
                )
            elif isinstance(mvalue, (int, float)):
                conn.execute(
                    "INSERT OR REPLACE INTO precomputed_results (factor_id, metric_name, metric_value, metric_meta, computed_at) VALUES (?, ?, ?, NULL, ?)",
                    [factor_id, mname, mvalue, now],
                )
            else:
                meta_val = json.dumps({"raw": mvalue})
                conn.execute(
                    "INSERT OR REPLACE INTO precomputed_results (factor_id, metric_name, metric_value, metric_meta, computed_at) VALUES (?, ?, NULL, ?, ?)",
                    [factor_id, mname, meta_val, now],
                )


def get_factor_by_id(factor_id: str) -> Optional[FactorSpec]:
    conn = _get_conn()
    result = conn.execute(
        "SELECT spec_json FROM factor_metadata WHERE factor_id = ?", [factor_id]
    ).fetchone()
    conn.close()

    if result is not None:
        return FactorSpec.model_validate_json(result[0])

    # DB 中未找到，检查 Demo 因子
    for demo in DEMO_FACTORS:
        if demo["factor_id"] == factor_id:
            return FactorSpec(
                factor_id=demo["factor_id"],
                name=demo["factor_id"],
                name_cn=demo["name_cn"],
                version="1.0.0",
                description=demo["description"],
                category=demo["category"],
                expected_direction=demo["expected_direction"],
                base=demo["base"],
                transform=demo["transform"],
                params=demo["params"],
                inputs=[],
                frequency="1d",
                availability="after_close",
                availability_lag=1,
                min_window=abs(demo["params"].get("window", 20)),
                universe_rule="historical_all_a",
                source=demo["source"],
            )

    return None


def get_all_factors(category: str = None) -> list[FactorSpec]:
    conn = _get_conn()
    if category:
        df = conn.execute(
            "SELECT spec_json FROM factor_metadata WHERE category = ? ORDER BY factor_id",
            [category],
        ).df()
    else:
        df = conn.execute(
            "SELECT spec_json FROM factor_metadata ORDER BY factor_id"
        ).df()
    conn.close()
    return [FactorSpec.model_validate_json(r) for r in df["spec_json"]]


def get_precomputed_metrics(factor_id: str) -> dict:
    conn = _get_conn()
    df = conn.execute(
        "SELECT metric_name, metric_value, metric_meta FROM precomputed_results WHERE factor_id = ?",
        [factor_id],
    ).df()
    conn.close()
    result = {}
    for _, r in df.iterrows():
        if r["metric_value"] is not None and not (isinstance(r["metric_value"], float) and pd.isna(r["metric_value"])):
            result[r["metric_name"]] = r["metric_value"]
        elif r["metric_meta"] is not None:
            meta = json.loads(r["metric_meta"])
            result[r["metric_name"]] = meta.get("raw")
    return result