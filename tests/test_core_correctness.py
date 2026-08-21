import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import uuid

from engine.data_aligner import align_factor_returns, compute_forward_returns
from engine.data_loader import build_snapshots, get_ohlcv_data, _query_parquet_with_filters
from engine.duplicate_detect import find_formula_duplicates
from engine.evidence_engine import generate_audit_result, generate_evidence_records
from engine.factor_computer import compute_factor_values, load_aligned_data
from engine.hash_utils import compute_evidence_hash
from engine.quality_check import check_negative_window
from engine.run_recorder import save_run
from engine.session_context import build_cache_context, contextual_cache_key, select_factor
from engine.stress_test import (
    _retention_and_verdict,
    _test_market_cap_neutralize,
    _test_remove_micro_cap,
    summarize_stress_results,
)
from engine.traditional_eval import compute_daily_rank_ic, evaluate_factor
from models.factor_spec import FactorSpec


def _spec(factor_id="factor_a", formula=None):
    return FactorSpec(
        factor_id=factor_id,
        name=factor_id,
        name_cn=factor_id,
        formula=formula,
        base="custom_formula" if formula else "return",
        params={"window": 2},
        source="custom" if formula else "builtin",
    )


def _write_source_csv(path, rows):
    columns = [
        "股票代码", "股票名称", "交易日期", "开盘价", "最高价", "最低价",
        "收盘价", "前收盘价", "成交量", "成交额", "流通市值", "总市值",
        "净利润TTM", "现金流TTM", "净利润(当季)", "新版申万一级行业名称",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    content = "数据来源测试\n" + frame.to_csv(index=False)
    path.write_bytes(content.encode("gbk"))


def test_build_snapshots_can_limit_output_to_one_week(tmp_path):
    source_dir = tmp_path / "csv"
    snapshot_dir = tmp_path / "snapshot"
    source_dir.mkdir()
    _write_source_csv(source_dir / "a.csv", [
        ["sh600001", "测试甲", "2025-09-19", 9, 10, 8, 9.5, 9, 100, 1000,
         9000, 10000, 110, 120, 30, "行业甲"],
        ["sh600001", "测试甲", "2025-09-22", 10, 11, 9, 10.5, 9.5, 110, 1100,
         9100, 10100, 111, 121, 31, "行业甲"],
        ["sh600001", "测试甲", "2025-09-26", 11, 12, 10, 11.5, 10.5, 120, 1200,
         9200, 10200, 112, 122, 32, "行业甲"],
    ])
    _write_source_csv(source_dir / "b.csv", [
        ["sz000002", "测试乙", "2025-09-24", 20, 21, 19, 20.5, 20, 200, 2000,
         19000, 20000, 210, 220, 40, "行业乙"],
        ["sz000002", "测试乙", "2025-09-29", 21, 22, 20, 21.5, 20.5, 210, 2100,
         19100, 20100, 211, 221, 41, "行业乙"],
    ])

    build_snapshots(
        source_dir=source_dir,
        snapshot_dir=snapshot_dir,
        date_start="2025-09-22",
        date_end="2025-09-26",
    )

    ohlcv = pd.read_parquet(snapshot_dir / "daily_ohlcv.parquet")
    basic = pd.read_parquet(snapshot_dir / "daily_basic.parquet")
    stocks = pd.read_parquet(snapshot_dir / "stock_basic.parquet")

    assert len(ohlcv) == len(basic) == 3
    assert ohlcv["trade_date"].min() == pd.Timestamp("2025-09-22")
    assert ohlcv["trade_date"].max() == pd.Timestamp("2025-09-26")
    assert ohlcv["ts_code"].nunique() == len(stocks) == 2
    assert "net_profit_ttm" in basic.columns
    assert "cash_flow_ttm" in basic.columns
    assert "net_profit_quarter" in basic.columns
    assert "pe_ttm" not in basic.columns


def test_data_source_path_can_be_overridden_by_environment(monkeypatch, tmp_path):
    from config import _configured_path

    override = tmp_path / "portable-source"
    monkeypatch.setenv("FACTORGUARD_TEST_SOURCE", str(override))

    assert _configured_path("FACTORGUARD_TEST_SOURCE", "unused") == override


def test_parquet_filters_use_bound_parameters(tmp_path):
    path = tmp_path / "quotes.parquet"
    pd.DataFrame({
        "ts_code": ["A", "B"],
        "trade_date": pd.to_datetime(["2025-09-24", "2025-09-25"]),
        "close": [10.0, 20.0],
    }).to_parquet(path, index=False)

    result = _query_parquet_with_filters(
        path, "2025-09-24", "2025-09-25", ["A' OR 1=1 --"]
    )

    assert result.empty


def test_missing_snapshot_does_not_implicitly_build_from_csv(monkeypatch, tmp_path):
    import engine.data_loader as data_loader

    missing = tmp_path / "daily_ohlcv.parquet"
    monkeypatch.setattr(data_loader, "OHLCV_PARQUET", missing)
    monkeypatch.setattr(
        data_loader,
        "build_snapshots",
        lambda: pytest.fail("snapshot construction must be explicit"),
    )

    with pytest.raises(FileNotFoundError, match="显式运行"):
        get_ohlcv_data()


def test_forward_return_uses_t_plus_one_plus_h():
    df = pd.DataFrame({
        "ts_code": ["A"] * 7,
        "trade_date": pd.date_range("2026-01-01", periods=7),
        "open": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0],
        "volume": [100] * 7,
    })

    result = compute_forward_returns(df, [1, 5])

    assert result.loc[0, "forward_return_1d"] == pytest.approx(12 / 11 - 1)
    assert result.loc[0, "forward_return_5d"] == pytest.approx(16 / 11 - 1)
    assert pd.isna(result.loc[5, "forward_return_1d"])


def test_coverage_is_measured_before_dropping_missing_factors():
    rows = []
    for date in pd.date_range("2026-01-01", periods=2):
        for index in range(10):
            rows.append({
                "ts_code": f"S{index:02d}",
                "trade_date": date,
                "factor_value": np.nan if index in {0, 1} else float(index),
                "forward_return": float(index) / 100,
            })
    df = pd.DataFrame(rows)

    daily = compute_daily_rank_ic(df)
    result = evaluate_factor(df, daily_rank_ic=daily)

    assert result["coverage"] == pytest.approx(0.8)
    assert list(daily["coverage"].values()) == pytest.approx([0.8, 0.8])


def test_missing_market_cap_is_untested_not_passed():
    df = pd.DataFrame({
        "ts_code": [f"S{i:02d}" for i in range(10)],
        "trade_date": [pd.Timestamp("2026-01-01")] * 10,
        "factor_value": range(10),
        "forward_return": range(10),
    })

    micro = _test_remove_micro_cap(df, 0.02)
    neutral = _test_market_cap_neutralize(df, 0.02)
    summary = summarize_stress_results([micro, neutral])

    assert micro["verdict"] == neutral["verdict"] == "untested"
    assert micro["retention_ratio"] is None
    assert summary["overall_verdict"] == "untested"


def test_alignment_preserves_market_cap_for_stress_tests():
    dates = pd.date_range("2026-01-01", periods=4)
    rows = []
    basics = []
    factors = []
    for stock_index in range(12):
        code = f"S{stock_index:02d}"
        for date_index, date in enumerate(dates):
            rows.append({
                "ts_code": code,
                "trade_date": date,
                "open": 10 + stock_index + date_index * (stock_index + 1) / 100,
                "close": 10 + stock_index,
                "volume": 100,
            })
            basics.append({
                "ts_code": code,
                "trade_date": date,
                "total_mv": float((stock_index + 1) * 1_000_000),
            })
            factors.append({
                "ts_code": code,
                "trade_date": date,
                "factor_value": float(stock_index),
            })

    aligned = align_factor_returns(
        pd.DataFrame(factors),
        pd.DataFrame(rows),
        pd.DataFrame(basics),
        forward_period=1,
    )

    assert "total_mv" in aligned.columns
    assert aligned["total_mv"].notna().all()
    assert _test_remove_micro_cap(aligned, 0.02)["verdict"] != "untested"
    assert _test_market_cap_neutralize(aligned, 0.02)["verdict"] != "untested"


def test_formula_duplicate_scan_uses_score_contract():
    selected = _spec("selected", "delay(close, 1) / close - 1")
    duplicate = _spec("duplicate", "delay(close, 1) / close - 1")
    unrelated = _spec("unrelated", "rolling_mean(volume, 20)")

    found = find_formula_duplicates(selected, [selected, unrelated, duplicate])

    assert found[0]["factor_id"] == "duplicate"
    assert found[0]["score"] > 0.8
    assert all(item["factor_id"] != "selected" for item in found)


def test_direction_flip_fails_even_with_high_absolute_retention():
    ratio, direction_kept, verdict = _retention_and_verdict(0.02, -0.03)

    assert ratio == pytest.approx(1.5)
    assert direction_kept is False
    assert verdict == "fail"


def test_select_factor_clears_previous_active_results():
    state = {
        "selected_factor_id": "old",
        "aligned_data": pd.DataFrame({"x": [1]}),
        "aligned_context": {"factor_id": "old", "forward_period": 5},
        "eval_results": {"rank_ic_mean": 0.1},
        "audit_results": {"traditional_eval": {}},
        "audit_run_id": "run-old",
        "data_snapshot_hash": "uploaded:old",
    }

    select_factor(state, _spec("new"))

    assert state["selected_factor_id"] == "new"
    assert "aligned_data" not in state
    assert "eval_results" not in state
    assert "audit_run_id" not in state
    assert "data_snapshot_hash" not in state
    assert state["audit_results"] == {}


def test_cache_key_changes_with_period_range_and_factor_definition():
    state = {}
    select_factor(state, _spec("factor_a"))

    base = contextual_cache_key(
        "eval", build_cache_context(state, forward_period=5, time_range="全量")
    )
    different_period = contextual_cache_key(
        "eval", build_cache_context(state, forward_period=10, time_range="全量")
    )
    different_range = contextual_cache_key(
        "eval", build_cache_context(state, forward_period=5, time_range="近3年")
    )
    select_factor(state, _spec("factor_a", "delay(close, 1)"))
    different_definition = contextual_cache_key(
        "eval", build_cache_context(state, forward_period=5, time_range="全量")
    )

    assert len({base, different_period, different_range, different_definition}) == 4


def test_uploaded_values_define_the_data_snapshot_identity():
    first_state = {}
    second_state = {}
    first = pd.DataFrame({"ts_code": ["A"], "trade_date": ["2026-01-01"], "factor_value": [1.0]})
    second = first.assign(factor_value=2.0)

    select_factor(first_state, _spec("upload"), factor_df=first)
    select_factor(second_state, _spec("upload"), factor_df=second)

    assert first_state["data_snapshot_hash"].startswith("uploaded:")
    assert first_state["data_snapshot_hash"] != second_state["data_snapshot_hash"]


def test_load_aligned_data_rejects_mismatched_cached_context(monkeypatch):
    state = {
        "selected_factor_id": "new",
        "aligned_data": pd.DataFrame({"sentinel": [1]}),
        "aligned_context": {"factor_id": "old", "forward_period": 5},
    }
    monkeypatch.setattr("engine.data_loader.get_ohlcv_data", lambda: (_ for _ in ()).throw(FileNotFoundError()))

    assert load_aligned_data(state, 5) is None
    assert "aligned_data" not in state


def test_missing_statistics_or_key_tests_are_insufficient():
    evaluation = {
        "coverage": 0.98,
        "max_delay": 1,
        "ic_p_value": None,
        "source": "precomputed",
    }

    audit = generate_audit_result("R001", {}, evaluation, {}, {}, {})

    assert audit.conclusion == "insufficient"
    assert audit.evidence_dimensions["统计支持"] == "untested"
    assert audit.evidence_dimensions["压力稳健性"] == "untested"
    assert audit.evidence_dimensions["信息独立性"] == "untested"


def test_missing_stress_results_still_emit_untested_evidence():
    records = generate_evidence_records(
        {"coverage": 0.98, "max_delay": 1, "ic_p_value": 0.001},
        {},
        {"source": "computed", "duplicates_found": 0},
        {},
    )

    stress_records = [record for record in records if record.dimension == "压力稳健性"]
    assert len(stress_records) == 1
    assert stress_records[0].severity == "untested"


def test_future_reference_quality_failure_is_invalid():
    evaluation = {
        "coverage": 0.98,
        "max_delay": -1,
        "ic_p_value": 0.001,
        "quality_checks": [{"evidence_id": "QC-WINDOW-001", "severity": "fail"}],
    }

    audit = generate_audit_result("demo_future_leak", {}, evaluation, {}, {}, {})

    assert audit.conclusion == "invalid"


def test_significant_rank_ic_in_wrong_expected_direction_is_not_supported():
    evaluation = {
        "coverage": 0.98,
        "max_delay": 1,
        "rank_ic_mean": -0.03,
        "ic_p_value": 0.001,
    }
    stress = {
        "source": "computed",
        "test_results": [{"verdict": "pass", "retention_ratio": 0.9}],
    }
    duplicate = {"source": "computed", "duplicates_found": 0}
    spec = _spec("wrong_direction")
    spec.expected_direction = "higher"

    audit = generate_audit_result(
        spec.factor_id, spec, evaluation, stress, duplicate, {}
    )

    assert audit.conclusion == "insufficient"
    assert audit.evidence_dimensions["统计支持"] == "fail"
    stats_record = next(
        record for record in audit.evidence_records if record.dimension == "统计支持"
    )
    assert stats_record.metrics["direction_matches"] is False


def test_negative_window_is_rejected_even_without_formula():
    spec = _spec("demo_future")
    spec.formula = None
    spec.params = {"window": -5}

    result = check_negative_window(spec)

    assert result["passed"] is False
    assert result["severity"] == "fail"


def test_hash_covers_all_deterministic_evidence():
    common = (_spec("R001"), "snapshot", {"forward_period": 5}, {"coverage": 0.9})
    base = compute_evidence_hash(*common, {"test_results": []}, {}, {})

    assert compute_evidence_hash(*common, {"test_results": [{"verdict": "fail"}]}, {}, {}) != base
    assert compute_evidence_hash(*common, {"test_results": []}, {"overall_verdict": "不相似"}, {}) != base
    assert compute_evidence_hash(*common, {"test_results": []}, {}, {"matrix": [[1]]}) != base


def test_custom_formula_is_executable_without_eval():
    df = pd.DataFrame({
        "ts_code": ["A"] * 4,
        "trade_date": pd.date_range("2026-01-01", periods=4),
        "close": [10.0, 11.0, 12.0, 14.0],
        "pre_close": [9.0, 10.0, 11.0, 12.0],
        "volume": [100] * 4,
    })
    spec = _spec("custom", "delay(close, 1) / delay(close, 2) - 1")

    result = compute_factor_values(df, spec)

    assert result.loc[2, "factor_value"] == pytest.approx(11 / 10 - 1)


def test_master_financial_proxy_is_computable_but_timing_remains_untested():
    dates = pd.date_range("2026-01-01", periods=2)
    rows = []
    for date_index, date in enumerate(dates):
        for stock_index in range(12):
            rows.append({
                "ts_code": f"S{stock_index:02d}",
                "trade_date": date,
                "net_profit_ttm": 100 + stock_index + date_index,
                "net_assets": 1000 + stock_index * 10,
            })
    spec = FactorSpec(
        factor_id="master_capital_efficiency",
        name="master_capital_efficiency",
        name_cn="资本效率代理",
        formula="rank_cs(net_profit_ttm / net_assets)",
        base="master_proxy",
        source="master_proxy",
        availability="financial_period_end_unverified",
        inputs=["net_profit_ttm", "net_assets"],
    )

    values = compute_factor_values(pd.DataFrame(rows), spec)

    assert values is not None
    assert values["factor_value"].notna().all()
    audit = generate_audit_result(
        spec.factor_id,
        spec,
        {
            "coverage": 1.0,
            "max_delay": 1,
            "rank_ic_mean": 0.02,
            "ic_p_value": 0.001,
        },
        {
            "source": "computed",
            "test_results": [{"verdict": "pass", "retention_ratio": 0.9}],
        },
        {"source": "computed", "duplicates_found": 0},
        {},
    )
    assert audit.evidence_dimensions["时间正确性"] == "untested"
    assert audit.conclusion == "insufficient"


def test_builtin_factor_uses_its_base_and_transform_contract():
    close = pd.Series([100 + i + (i % 4) * 0.7 for i in range(35)], dtype=float)
    df = pd.DataFrame({
        "ts_code": ["A"] * len(close),
        "trade_date": pd.date_range("2026-01-01", periods=len(close)),
        "open": close - 0.2,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "pre_close": close.shift(1),
        "volume": np.arange(len(close)) + 100,
    })
    spec = _spec("R001")
    spec.params = {"window": 5, "norm": 20}
    spec.transform = "z"

    result = compute_factor_values(df, spec)
    raw = close.pct_change(5)
    rolling = raw.rolling(20, min_periods=5)
    expected = (raw - rolling.mean()) / rolling.std(ddof=0)

    assert result.loc[34, "factor_value"] == pytest.approx(expected.iloc[34])


def test_selected_custom_spec_is_used_without_factor_registry_entry(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=5)
    ohlcv = pd.DataFrame({
        "ts_code": ["A"] * 5,
        "trade_date": dates,
        "open": [10, 11, 12, 13, 14],
        "high": [11, 12, 13, 14, 15],
        "low": [9, 10, 11, 12, 13],
        "close": [10, 11, 12, 13, 14],
        "pre_close": [9, 10, 11, 12, 13],
        "volume": [100] * 5,
    })
    basic = pd.DataFrame({"ts_code": ["A"] * 5, "trade_date": dates, "total_mv": [1000] * 5})
    spec = _spec("custom_unregistered", "delay(close, 1) / delay(close, 2) - 1")
    state = {}
    select_factor(state, spec)

    monkeypatch.setattr("engine.data_loader.get_ohlcv_data", lambda: ohlcv.copy())
    monkeypatch.setattr("engine.data_loader.get_basic_data", lambda: basic.copy())
    monkeypatch.setattr(
        "engine.data_aligner.align_factor_returns",
        lambda factor_df, *_args, **_kwargs: factor_df.assign(forward_return=0.01),
    )

    result = load_aligned_data(state, 5)

    assert result is not None
    assert result.loc[2, "factor_value"] == pytest.approx(11 / 10 - 1)


def test_save_run_persists_custom_factor_and_hashes(monkeypatch):
    import duckdb
    import engine.factor_loader as factor_loader

    db_path = Path("tests") / "artifacts" / f"audit-{uuid.uuid4().hex}.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(factor_loader, "DB_PATH", db_path)
    spec = _spec("custom_persisted", "delay(close, 1)")
    state = {"selected_factor_spec": spec}

    try:
        run_id = save_run(
            spec.name_cn,
            spec.factor_id,
            "insufficient",
            "missing stress test",
            state,
            evidence_hash="evidence-1",
            report_hash="report-1",
            run_params={"forward_period": 5},
        )

        conn = duckdb.connect(str(db_path), read_only=True)
        row = conn.execute(
            "SELECT factor_id, conclusion, evidence_hash, report_hash FROM audit_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        conn.close()

        assert row == ("custom_persisted", "insufficient", "evidence-1", "report-1")
        assert "run_persistence_error" not in state
    finally:
        db_path.unlink(missing_ok=True)


def test_save_run_does_not_overwrite_existing_factor_metadata(monkeypatch):
    import duckdb
    import engine.factor_loader as factor_loader

    db_path = Path("tests") / "artifacts" / f"audit-{uuid.uuid4().hex}.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(factor_loader, "DB_PATH", db_path)
    original = _spec("R001")
    original.base = "return"
    state = {"selected_factor_spec": original}

    try:
        save_run(original.name_cn, original.factor_id, "insufficient", "first", state)
        state.pop("selected_factor_spec")
        save_run(original.name_cn, original.factor_id, "insufficient", "second", state)

        conn = duckdb.connect(str(db_path), read_only=True)
        spec_json = conn.execute(
            "SELECT spec_json FROM factor_metadata WHERE factor_id = 'R001'"
        ).fetchone()[0]
        conn.close()

        assert FactorSpec.model_validate_json(spec_json).base == "return"
    finally:
        db_path.unlink(missing_ok=True)


def test_factor_catalog_loads_without_creating_a_database(monkeypatch, tmp_path):
    import engine.factor_loader as factor_loader

    db_path = tmp_path / "missing" / "factor_master.duckdb"
    monkeypatch.setattr(factor_loader, "DB_PATH", db_path)

    factors = factor_loader.get_all_factors()

    assert len(factors) == 806
    assert not db_path.exists()
    assert factor_loader.get_factor_by_id("R001") is not None
    master = factor_loader.get_factor_by_id(
        "master_berkshire-quality_capital_efficiency"
    )
    assert master is not None
    assert master.source == "master_proxy"


def test_precomputed_metrics_load_without_creating_a_database(monkeypatch, tmp_path):
    import engine.factor_loader as factor_loader

    db_path = tmp_path / "missing" / "factor_master.duckdb"
    monkeypatch.setattr(factor_loader, "DB_PATH", db_path)

    metrics = factor_loader.get_precomputed_metrics("R001")

    assert metrics
    assert not db_path.exists()
