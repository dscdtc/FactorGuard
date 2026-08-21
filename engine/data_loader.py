"""
数据加载器模块
- 从本地 CSV 目录加载全量股票日线数据
- 标准化列名、合并、去重
- 生成 Parquet 快照供下游使用
- 支持 DuckDB 直接查询 Parquet 文件（高性能过滤）
"""
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from config import DATA_LOCAL, DATA_SNAPSHOT, OHLCV_PARQUET, BASIC_PARQUET, STOCK_BASIC_PARQUET

# ---------------------------------------------------------------------------
# 中文列名 → 英文标准化列名映射（基于实际 CSV 列名）
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    "股票代码": "ts_code",
    "股票名称": "name",
    "交易日期": "trade_date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "前收盘价": "pre_close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover_rate",
    "流通市值": "circ_mv",
    "总市值": "total_mv",
    "净利润TTM": "net_profit_ttm",
    "现金流TTM": "cash_flow_ttm",
    "总资产": "total_assets",
    "净资产": "net_assets",
    "总负债": "total_liability",
    "净利润(当季)": "net_profit_quarter",
    "新版申万一级行业名称": "industry_l1",
    "新版申万二级行业名称": "industry_l2",
    "新版申万三级行业名称": "industry_l3",
}

# 快照文件拆分方案
OHLCV_COLS = [
    "ts_code", "trade_date", "open", "high", "low", "close",
    "pre_close", "volume", "amount",
]

BASIC_COLS = [
    "ts_code", "trade_date", "circ_mv", "total_mv", "net_profit_ttm",
    "cash_flow_ttm", "total_assets", "net_assets", "total_liability",
    "net_profit_quarter", "turnover_rate",
]

STOCK_BASIC_COLS = [
    "ts_code", "name", "industry_l1", "industry_l2", "industry_l3",
]

NUMERIC_COLS = [
    "open", "high", "low", "close", "pre_close", "volume", "amount",
    "circ_mv", "total_mv", "net_profit_ttm", "cash_flow_ttm",
    "total_assets", "net_assets", "total_liability", "net_profit_quarter",
    "turnover_rate",
]

TEXT_COLS = ["ts_code", "name", "industry_l1", "industry_l2", "industry_l3"]


def _offline_mode() -> bool:
    return os.getenv("FACTORGUARD_OFFLINE_MODE", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _progress_bar(current: int, total: int, label: str = "", width: int = 50) -> None:
    """简单的控制台进度条"""
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    bar = "#" * filled + "." * (width - filled)
    sys.stdout.write(f"\r{label} [{bar}] {current}/{total} ({pct:.1%})")
    sys.stdout.flush()


def _read_single_csv(filepath: Path) -> pd.DataFrame | None:
    """读取单个 CSV 文件，返回标准化后的 DataFrame；失败返回 None"""
    try:
        # GBK 编码，跳过第一行（数据来源说明），第二行为表头
        df = pd.read_csv(
            filepath,
            encoding="gbk",
            skiprows=1,
            header=0,
            dtype=str,
            na_values=["", " ", "nan", "NaN", "None"],
            keep_default_na=False,
        )
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(
                filepath,
                encoding="gb18030",
                skiprows=1,
                header=0,
                dtype=str,
                na_values=["", " ", "nan", "NaN", "None"],
                keep_default_na=False,
            )
        except Exception:
            print(f"  [警告] 编码错误，跳过: {filepath.name}")
            return None
    except Exception:
        print(f"  [警告] 读取失败，跳过: {filepath.name}")
        return None

    if df.empty:
        return None

    # 去除列名两端空白
    df.columns = df.columns.str.strip()

    # 只保留映射中定义的列
    cols_to_keep = [c for c in COLUMN_MAP if c in df.columns]
    if not cols_to_keep:
        return None
    df = df[cols_to_keep].copy()

    # 重命名为英文标准列名
    df.rename(columns=COLUMN_MAP, inplace=True)

    return df


def _standardize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize one source file to stable dtypes used by Parquet writers."""
    frame = df.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame = frame.dropna(subset=["ts_code", "trade_date"])

    for column in NUMERIC_COLS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    for column in TEXT_COLS:
        if column in frame.columns:
            frame[column] = frame[column].astype("string")

    return (
        frame.sort_values(["ts_code", "trade_date"])
        .drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        .reset_index(drop=True)
    )


def _select_snapshot_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return a frame with a fixed schema even when a source CSV lacks a field."""
    selected = df.copy()
    for column in columns:
        if column not in selected.columns:
            if column in TEXT_COLS:
                selected[column] = pd.Series(pd.NA, index=selected.index, dtype="string")
            elif column == "trade_date":
                selected[column] = pd.Series(pd.NaT, index=selected.index, dtype="datetime64[ns]")
            else:
                selected[column] = float("nan")
    return selected[columns]


def load_all_csvs() -> pd.DataFrame:
    """遍历 DATA_LOCAL 下所有 CSV，合并为统一 DataFrame

    Returns
    -------
    pd.DataFrame
        按 (ts_code, trade_date) 排序去重后的全量数据
    """
    if not DATA_LOCAL.exists():
        raise FileNotFoundError(f"数据目录不存在: {DATA_LOCAL}")

    csv_files = sorted(DATA_LOCAL.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"数据目录下无 CSV 文件: {DATA_LOCAL}")

    total = len(csv_files)
    print(f"发现 {total} 个 CSV 文件，开始加载...")

    frames: list[pd.DataFrame] = []
    failed = 0

    for i, fp in enumerate(csv_files, 1):
        _progress_bar(i, total, label="加载 CSV")
        raw = _read_single_csv(fp)
        df = _standardize_frame(raw) if raw is not None else None
        if df is not None:
            frames.append(df)
        else:
            failed += 1

    print()  # 换行
    print(f"成功加载 {len(frames)} 个文件，跳过 {failed} 个")

    if not frames:
        raise RuntimeError("没有成功加载任何数据文件")

    print("合并 DataFrame...")
    merged = pd.concat(frames, ignore_index=True)

    # 排序去重
    sort_cols = ["ts_code", "trade_date"]
    merged = merged.sort_values(sort_cols).drop_duplicates(subset=sort_cols, keep="last")
    merged = merged.reset_index(drop=True)

    print(f"合并完成: {merged.shape[0]} 行 × {merged.shape[1]} 列")
    print(f"  股票数: {merged['ts_code'].nunique()}")
    print(f"  日期范围: {merged['trade_date'].min()} ~ {merged['trade_date'].max()}")

    return merged


def build_snapshots(
    source_dir: Path | None = None,
    snapshot_dir: Path | None = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> None:
    """Stream source CSVs into atomic Parquet snapshots with bounded memory.

    ``date_start`` and ``date_end`` are inclusive. They are primarily useful
    for building a small validation snapshot before processing full history.
    """
    source_dir = Path(source_dir or DATA_LOCAL)
    snapshot_dir = Path(snapshot_dir or DATA_SNAPSHOT)
    start = pd.Timestamp(date_start).normalize() if date_start else None
    end = pd.Timestamp(date_end).normalize() if date_end else None
    if start is not None and end is not None and start > end:
        raise ValueError("date_start must not be later than date_end")
    if not source_dir.exists():
        raise FileNotFoundError(f"数据目录不存在: {source_dir}")

    csv_files = sorted(source_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"数据目录下无 CSV 文件: {source_dir}")

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        "ohlcv": snapshot_dir / OHLCV_PARQUET.name,
        "basic": snapshot_dir / BASIC_PARQUET.name,
        "stock": snapshot_dir / STOCK_BASIC_PARQUET.name,
    }
    temporary = {name: path.with_name(path.name + ".building") for name, path in targets.items()}
    for path in temporary.values():
        path.unlink(missing_ok=True)

    writers: dict[str, pq.ParquetWriter] = {}
    stock_frames = []
    failed = 0
    outside_range = 0
    ohlcv_rows = 0
    basic_rows = 0

    try:
        total = len(csv_files)
        print(f"发现 {total} 个 CSV 文件，开始流式构建 Parquet 快照...")
        for index, filepath in enumerate(csv_files, 1):
            if index == 1 or index % 50 == 0 or index == total:
                _progress_bar(index, total, label="构建快照")

            raw = _read_single_csv(filepath)
            if raw is None:
                failed += 1
                continue
            frame = _standardize_frame(raw)
            if frame.empty:
                failed += 1
                continue
            if start is not None:
                frame = frame.loc[frame["trade_date"] >= start]
            if end is not None:
                frame = frame.loc[frame["trade_date"] <= end]
            if frame.empty:
                outside_range += 1
                continue

            ohlcv = _select_snapshot_columns(frame, OHLCV_COLS)
            basic = _select_snapshot_columns(frame, BASIC_COLS)
            for name, selected in (("ohlcv", ohlcv), ("basic", basic)):
                table = pa.Table.from_pandas(selected, preserve_index=False)
                if name not in writers:
                    writers[name] = pq.ParquetWriter(
                        temporary[name], table.schema, compression="zstd"
                    )
                writers[name].write_table(table)

            ohlcv_rows += len(ohlcv)
            basic_rows += len(basic)
            stock_source = _select_snapshot_columns(
                frame, ["trade_date"] + STOCK_BASIC_COLS
            )
            stock_frames.append(
                stock_source.sort_values("trade_date")
                .groupby("ts_code", as_index=False)
                .last()[STOCK_BASIC_COLS]
            )

        print()
        if not writers or not stock_frames:
            raise RuntimeError("没有成功加载任何数据文件")

        for writer in writers.values():
            writer.close()
        writers.clear()

        stock_basic = (
            pd.concat(stock_frames, ignore_index=True)
            .drop_duplicates(subset="ts_code", keep="last")
            .sort_values("ts_code")
            .reset_index(drop=True)
        )
        stock_basic.to_parquet(temporary["stock"], index=False, compression="zstd")

        for name, target in targets.items():
            temporary[name].replace(target)

        print(
            f"快照生成完毕: OHLCV {ohlcv_rows:,} 行，basic {basic_rows:,} 行，"
            f"股票 {len(stock_basic):,} 只，读取失败 {failed} 个文件，"
            f"日期范围外 {outside_range} 个文件。"
        )
    except Exception:
        for writer in writers.values():
            writer.close()
        for path in temporary.values():
            path.unlink(missing_ok=True)
        raise


def get_ohlcv_data(force_rebuild: bool = False,
                    date_start: Optional[str] = None,
                    date_end: Optional[str] = None,
                    ts_codes: Optional[list[str]] = None) -> pd.DataFrame:
    """获取 OHLCV 数据（使用 DuckDB 直接查询 Parquet 文件）

    Parameters
    ----------
    force_rebuild : bool
        是否强制重建快照（忽略已有 Parquet 文件）
    date_start : str, optional
        起始日期过滤（YYYY-MM-DD），利用 DuckDB 下推过滤
    date_end : str, optional
        结束日期过滤（YYYY-MM-DD），利用 DuckDB 下推过滤
    ts_codes : list[str], optional
        股票代码列表过滤，利用 DuckDB 下推过滤

    Returns
    -------
    pd.DataFrame
        OHLCV 数据（仅包含 OHLCV 列）
    """
    if not force_rebuild and _offline_mode():
        raise FileNotFoundError("FactorGuard offline mode: realtime snapshots are disabled")
    if not force_rebuild and OHLCV_PARQUET.exists():
        if date_start or date_end or ts_codes:
            return _query_parquet_with_filters(
                OHLCV_PARQUET, date_start, date_end, ts_codes
            )
        print(f"从快照加载: {OHLCV_PARQUET}")
        df = pd.read_parquet(OHLCV_PARQUET)
        print(f"  加载完成: {df.shape[0]} 行 × {df.shape[1]} 列")
        return df

    if not force_rebuild:
        raise FileNotFoundError(
            f"行情快照不存在: {OHLCV_PARQUET}。"
            "请先显式运行 scripts/build_snapshots.py 构建快照。"
        )

    print("force_rebuild=True，强制重建快照...")
    build_snapshots()
    if date_start or date_end or ts_codes:
        return _query_parquet_with_filters(
            OHLCV_PARQUET, date_start, date_end, ts_codes
        )
    df = pd.read_parquet(OHLCV_PARQUET)
    return df


def _query_parquet_with_filters(parquet_path, date_start, date_end, ts_codes):
    """使用 DuckDB 直接查询 Parquet 文件，支持下推过滤

    Parameters
    ----------
    parquet_path : Path
        Parquet 文件路径
    date_start : str or None
    date_end : str or None
    ts_codes : list[str] or None

    Returns
    -------
    pd.DataFrame
    """
    conn = duckdb.connect(":memory:")
    conditions = []
    parameters = []
    if date_start:
        conditions.append("trade_date >= ?")
        parameters.append(pd.Timestamp(date_start).to_pydatetime())
    if date_end:
        conditions.append("trade_date <= ?")
        parameters.append(pd.Timestamp(date_end).to_pydatetime())
    if ts_codes:
        placeholders = ", ".join("?" for _ in ts_codes)
        conditions.append(f"ts_code IN ({placeholders})")
        parameters.extend(str(code) for code in ts_codes)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    safe_path = str(Path(parquet_path).resolve()).replace("'", "''")
    sql = f"SELECT * FROM read_parquet('{safe_path}') WHERE {where_clause}"
    print(f"[DuckDB] 查询 Parquet: {parquet_path.name} | 条件: {where_clause}")
    try:
        df = conn.execute(sql, parameters).df()
    finally:
        conn.close()
    print(f"  加载完成: {df.shape[0]} 行 × {df.shape[1]} 列")
    return df


# ---------------------------------------------------------------------------
# 便捷函数：获取各类快照数据
# ---------------------------------------------------------------------------
def get_basic_data(force_rebuild: bool = False,
                   date_start: Optional[str] = None,
                   date_end: Optional[str] = None,
                   ts_codes: Optional[list[str]] = None) -> pd.DataFrame:
    """获取 daily_basic 数据（基本面/估值），支持 DuckDB 过滤查询"""
    if not force_rebuild and _offline_mode():
        raise FileNotFoundError("FactorGuard offline mode: realtime snapshots are disabled")
    if not force_rebuild and BASIC_PARQUET.exists():
        if date_start or date_end or ts_codes:
            return _query_parquet_with_filters(
                BASIC_PARQUET, date_start, date_end, ts_codes
            )
        print(f"从快照加载: {BASIC_PARQUET}")
        df = pd.read_parquet(BASIC_PARQUET)
        print(f"  加载完成: {df.shape[0]} 行 × {df.shape[1]} 列")
        return df
    if not force_rebuild:
        raise FileNotFoundError(
            f"基础指标快照不存在: {BASIC_PARQUET}。"
            "请先显式运行 scripts/build_snapshots.py 构建快照。"
        )
    print("force_rebuild=True，强制重建快照...")
    build_snapshots()
    if date_start or date_end or ts_codes:
        return _query_parquet_with_filters(
            BASIC_PARQUET, date_start, date_end, ts_codes
        )
    return pd.read_parquet(BASIC_PARQUET)


def get_stock_basic_data(force_rebuild: bool = False) -> pd.DataFrame:
    """获取 stock_basic 数据（股票基本信息/行业分类）"""
    if not force_rebuild and _offline_mode():
        raise FileNotFoundError("FactorGuard offline mode: realtime snapshots are disabled")
    if not force_rebuild and STOCK_BASIC_PARQUET.exists():
        print(f"从快照加载: {STOCK_BASIC_PARQUET}")
        df = pd.read_parquet(STOCK_BASIC_PARQUET)
        print(f"  加载完成: {df.shape[0]} 行 × {df.shape[1]} 列")
        return df
    if not force_rebuild:
        raise FileNotFoundError(
            f"股票基本信息快照不存在: {STOCK_BASIC_PARQUET}。"
            "请先显式运行 scripts/build_snapshots.py 构建快照。"
        )
    print("force_rebuild=True，强制重建快照...")
    build_snapshots()
    return pd.read_parquet(STOCK_BASIC_PARQUET)
