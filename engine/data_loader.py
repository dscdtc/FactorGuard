"""
数据加载器模块
- 从本地 CSV 目录加载全量股票日线数据
- 标准化列名、合并、去重
- 生成 Parquet 快照供下游使用
- 支持 DuckDB 直接查询 Parquet 文件（高性能过滤）
"""
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import duckdb

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
    "流通市值": "circ_mv",
    "总市值": "total_mv",
    "净利润TTM": "pe_ttm",
    "现金流TTM": "pcf_ttm",
    "总资产": "total_assets",
    "净资产": "net_assets",
    "总负债": "total_liability",
    "净利润(当季)": "net_profit_yoy",
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
    "ts_code", "trade_date", "circ_mv", "total_mv", "pe_ttm",
    "pcf_ttm", "total_assets", "net_assets", "total_liability",
    "net_profit_yoy",
]

STOCK_BASIC_COLS = [
    "ts_code", "name", "industry_l1", "industry_l2", "industry_l3",
]


def _progress_bar(current: int, total: int, label: str = "", width: int = 50) -> None:
    """简单的控制台进度条"""
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
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
        df = _read_single_csv(fp)
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

    # 将 trade_date 转为日期类型（容错）
    merged["trade_date"] = pd.to_datetime(
        merged["trade_date"], errors="coerce"
    ).dt.date
    # 去除 trade_date 解析失败的行
    before = len(merged)
    merged = merged.dropna(subset=["trade_date"])
    if len(merged) < before:
        print(f"  去除 trade_date 无效行: {before - len(merged)}")

    # 数值列类型转换
    numeric_cols = [
        "open", "high", "low", "close", "pre_close",
        "volume", "amount", "circ_mv", "total_mv",
        "pe_ttm", "pcf_ttm", "total_assets", "net_assets",
        "total_liability", "net_profit_yoy",
    ]
    for col in numeric_cols:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")

    # 排序去重
    sort_cols = ["ts_code", "trade_date"]
    merged = merged.sort_values(sort_cols).drop_duplicates(subset=sort_cols, keep="last")
    merged = merged.reset_index(drop=True)

    print(f"合并完成: {merged.shape[0]} 行 × {merged.shape[1]} 列")
    print(f"  股票数: {merged['ts_code'].nunique()}")
    print(f"  日期范围: {merged['trade_date'].min()} ~ {merged['trade_date'].max()}")

    return merged


def build_snapshots() -> None:
    """调用 load_all_csvs()，将结果拆分为三个 Parquet 快照文件"""
    df = load_all_csvs()

    # 确保快照目录存在
    DATA_SNAPSHOT.mkdir(parents=True, exist_ok=True)

    # --- daily_ohlcv ---
    print(f"\n写入 {OHLCV_PARQUET} ...")
    ohlcv = df[[c for c in OHLCV_COLS if c in df.columns]].copy()
    ohlcv.to_parquet(OHLCV_PARQUET, index=False)
    print(f"  完成: {ohlcv.shape[0]} 行 × {ohlcv.shape[1]} 列")

    # --- daily_basic ---
    print(f"写入 {BASIC_PARQUET} ...")
    basic = df[[c for c in BASIC_COLS if c in df.columns]].copy()
    basic.to_parquet(BASIC_PARQUET, index=False)
    print(f"  完成: {basic.shape[0]} 行 × {basic.shape[1]} 列")

    # --- stock_basic ---
    print(f"写入 {STOCK_BASIC_PARQUET} ...")
    sb_cols = [c for c in STOCK_BASIC_COLS if c in df.columns]
    stock_basic = df[sb_cols].copy()
    # 每个 ts_code 取最后一个非空值
    stock_basic = (
        stock_basic
        .sort_values("trade_date")
        .groupby("ts_code", as_index=False)
        .last()
    )
    # 对 industry 列用 ffill 填充
    for col in ["industry_l1", "industry_l2", "industry_l3"]:
        if col in stock_basic.columns:
            stock_basic[col] = stock_basic[col].replace("", None)
            stock_basic[col] = stock_basic.groupby("ts_code")[col].ffill().bfill()
    # 再次去重取最后一条
    stock_basic = stock_basic.drop_duplicates(subset="ts_code", keep="last")
    stock_basic = stock_basic.reset_index(drop=True)
    stock_basic.to_parquet(STOCK_BASIC_PARQUET, index=False)
    print(f"  完成: {stock_basic.shape[0]} 行 × {stock_basic.shape[1]} 列")

    print("\n快照生成完毕。")


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
    if not force_rebuild and OHLCV_PARQUET.exists():
        if date_start or date_end or ts_codes:
            return _query_parquet_with_filters(
                OHLCV_PARQUET, date_start, date_end, ts_codes
            )
        print(f"从快照加载: {OHLCV_PARQUET}")
        df = pd.read_parquet(OHLCV_PARQUET)
        print(f"  加载完成: {df.shape[0]} 行 × {df.shape[1]} 列")
        return df

    if force_rebuild:
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
    if date_start:
        conditions.append(f"trade_date >= '{date_start}'")
    if date_end:
        conditions.append(f"trade_date <= '{date_end}'")
    if ts_codes:
        codes_str = ", ".join(f"'{c}'" for c in ts_codes)
        conditions.append(f"ts_code IN ({codes_str})")

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"SELECT * FROM '{parquet_path}' WHERE {where_clause}"
    print(f"[DuckDB] 查询 Parquet: {parquet_path.name} | 条件: {where_clause}")
    df = conn.execute(sql).df()
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
    if not force_rebuild and BASIC_PARQUET.exists():
        if date_start or date_end or ts_codes:
            return _query_parquet_with_filters(
                BASIC_PARQUET, date_start, date_end, ts_codes
            )
        print(f"从快照加载: {BASIC_PARQUET}")
        df = pd.read_parquet(BASIC_PARQUET)
        print(f"  加载完成: {df.shape[0]} 行 × {df.shape[1]} 列")
        return df
    if force_rebuild:
        print("force_rebuild=True，强制重建快照...")
    build_snapshots()
    if date_start or date_end or ts_codes:
        return _query_parquet_with_filters(
            BASIC_PARQUET, date_start, date_end, ts_codes
        )
    return pd.read_parquet(BASIC_PARQUET)


def get_stock_basic_data(force_rebuild: bool = False) -> pd.DataFrame:
    """获取 stock_basic 数据（股票基本信息/行业分类）"""
    if not force_rebuild and STOCK_BASIC_PARQUET.exists():
        print(f"从快照加载: {STOCK_BASIC_PARQUET}")
        df = pd.read_parquet(STOCK_BASIC_PARQUET)
        print(f"  加载完成: {df.shape[0]} 行 × {df.shape[1]} 列")
        return df
    if force_rebuild:
        print("force_rebuild=True，强制重建快照...")
    build_snapshots()
    return pd.read_parquet(STOCK_BASIC_PARQUET)