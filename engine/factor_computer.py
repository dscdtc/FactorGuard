"""
因子值计算与对齐模块

从 OHLCV 数据中根据因子 spec 计算因子值，并对齐前瞻收益。
"""
import hashlib
import json

import numpy as np
import pandas as pd

from engine.formula_parser import (
    BinOpNode, FieldNode, FormulaParser, FuncCallNode, NumberNode, UnaryOpNode,
)


def _snapshot_data_identity() -> str | None:
    """Identify the local parquet snapshot without hashing hundreds of MB per page."""
    from config import BASIC_PARQUET, OHLCV_PARQUET

    files = [path for path in (OHLCV_PARQUET, BASIC_PARQUET) if path.exists()]
    if not files:
        return None
    metadata = [
        {"path": path.name, "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
        for path in files
    ]
    payload = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    return "snapshot-meta:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _evaluate_formula_node(node, df: pd.DataFrame) -> pd.Series | float:
    if isinstance(node, NumberNode):
        return node.value
    if isinstance(node, FieldNode):
        if node.name not in df.columns:
            raise ValueError(f"公式字段不可用: {node.name}")
        return pd.to_numeric(df[node.name], errors="coerce")
    if isinstance(node, UnaryOpNode):
        value = _evaluate_formula_node(node.operand, df)
        return -value
    if isinstance(node, BinOpNode):
        left = _evaluate_formula_node(node.left, df)
        right = _evaluate_formula_node(node.right, df)
        return {"+": lambda: left + right, "-": lambda: left - right,
                "*": lambda: left * right, "/": lambda: left / right}[node.op]()
    if not isinstance(node, FuncCallNode):
        raise ValueError("不支持的公式节点")

    args = [_evaluate_formula_node(arg, df) for arg in node.args]
    value = args[0] if args else None
    if node.name in {"delay", "ts_mean", "ts_sum", "ts_std", "ts_min", "ts_max"}:
        if not isinstance(value, pd.Series) or len(args) < 2:
            raise ValueError(f"{node.name} 参数无效")
        window = int(args[1])
        grouped = value.groupby(df["ts_code"], sort=False)
        if node.name == "delay":
            return grouped.shift(window)
        min_periods = max(1, window // 2)
        rolling = grouped.rolling(window, min_periods=min_periods)
        method = {"ts_mean": "mean", "ts_sum": "sum", "ts_std": "std",
                  "ts_min": "min", "ts_max": "max"}[node.name]
        result = getattr(rolling, method)().reset_index(level=0, drop=True)
        return result.reindex(df.index)
    if not isinstance(value, pd.Series):
        raise ValueError(f"{node.name} 第一个参数必须是序列")
    if node.name == "rank_cs":
        return value.groupby(df["trade_date"]).rank(pct=True)
    if node.name == "zscore_cs":
        return value.groupby(df["trade_date"]).transform(
            lambda x: (x - x.mean()) / x.std(ddof=0) if x.std(ddof=0) else np.nan
        )
    if node.name == "log":
        return np.log(value.where(value > 0))
    if node.name == "abs":
        return value.abs()
    if node.name == "sign":
        return np.sign(value)
    if node.name == "sqrt":
        return np.sqrt(value.where(value >= 0))
    raise ValueError(f"不支持的公式函数: {node.name}")


def _compute_formula_values(df: pd.DataFrame, formula: str) -> pd.Series:
    parsed = FormulaParser().parse(formula)
    if not parsed.valid or parsed.errors:
        raise ValueError("; ".join(parsed.errors) or "公式无效")
    result = _evaluate_formula_node(parsed.ast, df)
    if not isinstance(result, pd.Series):
        return pd.Series(result, index=df.index, dtype=float)
    return result


def _min_periods(window: int, floor: int = 5) -> int:
    return min(window, max(2, min(floor, window // 2 if window > 2 else 2)))


def _zscore(series: pd.Series, window: int) -> pd.Series:
    rolling = series.rolling(window, min_periods=_min_periods(window))
    return (series - rolling.mean()) / rolling.std(ddof=0).replace(0, np.nan)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=_min_periods(span, 3)).mean()


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    window = max(3, int(window))
    x = np.arange(window, dtype=float)
    x -= x.mean()
    denominator = float(np.sum(x * x))

    def calculate(values):
        if np.isnan(values).any():
            return np.nan
        return float(np.sum(x * (values - values.mean())) / denominator)

    return series.rolling(window, min_periods=window).apply(calculate, raw=True)


def _time_series_rank(series: pd.Series, window: int) -> pd.Series:
    def calculate(values):
        valid = values[~np.isnan(values)]
        if len(valid) == 0:
            return np.nan
        return float(pd.Series(valid).rank(pct=True).iloc[-1])

    return series.rolling(window, min_periods=_min_periods(window)).apply(calculate, raw=True)


def _compute_builtin_group(group: pd.DataFrame, spec) -> pd.Series:
    """Compute one built-in factor exactly from its base/transform contract."""
    params = getattr(spec, "params", {}) or {}
    base = getattr(spec, "base", "") or ""
    transform = getattr(spec, "transform", "raw") or "raw"
    window = int(params.get("window", 20))
    fast = int(params.get("fast", max(3, window // 3)))
    slow = int(params.get("slow", window))

    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required.difference(group.columns))
    if missing:
        raise ValueError(f"内置因子缺少 OHLCV 字段: {', '.join(missing)}")

    close = pd.to_numeric(group["close"], errors="coerce")
    open_ = pd.to_numeric(group["open"], errors="coerce")
    high = pd.to_numeric(group["high"], errors="coerce")
    low = pd.to_numeric(group["low"], errors="coerce")
    volume = pd.to_numeric(group["volume"], errors="coerce")
    returns = close.pct_change()

    if base == "return":
        signal = close.pct_change(window)
    elif base == "skip_return":
        signal = close.shift(int(params.get("skip", 5))).pct_change(window)
    elif base == "reversal":
        signal = -close.pct_change(window)
    elif base == "sma_gap":
        signal = close / close.rolling(window, min_periods=_min_periods(window)).mean() - 1
    elif base == "ema_gap":
        signal = close / _ema(close, window) - 1
    elif base == "dual_ema_gap":
        signal = (_ema(close, fast) - _ema(close, slow)) / close.replace(0, np.nan)
    elif base == "sma_slope":
        moving_average = close.rolling(window, min_periods=_min_periods(window)).mean()
        signal = _rolling_slope(moving_average, min(30, max(5, window // 2))) / close.replace(0, np.nan)
    elif base in {"range_position", "stoch"}:
        rolling_low = low.rolling(window, min_periods=_min_periods(window)).min()
        rolling_high = high.rolling(window, min_periods=_min_periods(window)).max()
        signal = (close - rolling_low) / (rolling_high - rolling_low).replace(0, np.nan) - 0.5
    elif base == "breakout":
        previous_high = high.shift(1).rolling(window, min_periods=_min_periods(window)).max()
        signal = close / previous_high.replace(0, np.nan) - 1
    elif base == "breakdown":
        previous_low = low.shift(1).rolling(window, min_periods=_min_periods(window)).min()
        signal = -(close / previous_low.replace(0, np.nan) - 1)
    elif base in {"rsi", "rsi_reversal"}:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=_min_periods(window)).mean()
        avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=_min_periods(window)).mean()
        rsi = 100 - 100 / (1 + avg_gain / avg_loss.replace(0, np.nan))
        signal = rsi / 100 - 0.5 if base == "rsi" else 0.5 - rsi / 100
    elif base == "atr_ratio":
        previous_close = close.shift(1)
        true_range = pd.concat(
            [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
        ).max(axis=1)
        signal = true_range.rolling(window, min_periods=_min_periods(window)).mean() / close.replace(0, np.nan)
    elif base == "range_ratio":
        signal = ((high - low) / close.replace(0, np.nan)).rolling(
            window, min_periods=_min_periods(window)
        ).mean()
    elif base == "realized_vol":
        signal = returns.rolling(window, min_periods=_min_periods(window)).std(ddof=0)
    elif base == "downside_vol":
        signal = returns.where(returns < 0, 0).rolling(window, min_periods=_min_periods(window)).std(ddof=0)
    elif base == "trend_strength":
        volatility = returns.rolling(window, min_periods=_min_periods(window)).std(ddof=0)
        signal = close.pct_change(window) / volatility.replace(0, np.nan)
    elif base == "efficiency":
        movement = close.diff().abs().rolling(window, min_periods=_min_periods(window)).sum()
        signal = (close - close.shift(window)).abs() / movement.replace(0, np.nan)
    elif base == "volume_ratio":
        signal = volume / volume.rolling(window, min_periods=_min_periods(window)).mean() - 1
    elif base == "volume_z":
        signal = _zscore(volume, window)
    elif base == "dollar_volume":
        dollar_volume = close * volume
        signal = dollar_volume / dollar_volume.rolling(window, min_periods=_min_periods(window)).mean() - 1
    elif base == "price_volume_corr":
        signal = returns.rolling(window, min_periods=_min_periods(window)).corr(volume.pct_change())
    elif base == "obv_slope":
        obv = (np.sign(close.diff()).fillna(0) * volume).cumsum()
        mean_volume = volume.rolling(window, min_periods=_min_periods(window)).mean()
        signal = _rolling_slope(obv, min(window, 60)) / mean_volume.replace(0, np.nan)
    elif base == "gap_sum":
        signal = (open_ / close.shift(1) - 1).rolling(window, min_periods=_min_periods(window)).sum()
    elif base == "intraday":
        signal = (close / open_.replace(0, np.nan) - 1).rolling(
            window, min_periods=_min_periods(window)
        ).mean()
    elif base in {"upper_wick", "lower_wick"}:
        top = pd.concat([open_, close], axis=1).max(axis=1)
        bottom = pd.concat([open_, close], axis=1).min(axis=1)
        wick = (high - top) if base == "upper_wick" else (bottom - low)
        signal = (wick / (high - low).replace(0, np.nan)).rolling(
            window, min_periods=_min_periods(window)
        ).mean()
    elif base == "drawdown":
        signal = close / close.rolling(window, min_periods=_min_periods(window)).max().replace(0, np.nan) - 1
    elif base == "ts_rank_close":
        signal = _time_series_rank(close, window) - 0.5
    elif base == "ts_rank_volume":
        signal = _time_series_rank(volume, window) - 0.5
    elif base == "ret_skew":
        signal = returns.rolling(window, min_periods=_min_periods(window, 10)).skew()
    elif base == "ret_kurt":
        signal = returns.rolling(window, min_periods=_min_periods(window, 10)).kurt()
    else:
        raise ValueError(f"未支持的内置因子基础定义: {base or '<empty>'}")

    norm = int(params.get("norm", max(20, window)))
    if transform in {"raw", "none"}:
        return signal
    if transform == "neg":
        return -signal
    if transform == "z":
        return _zscore(signal, norm)
    if transform == "delta":
        return signal - signal.shift(int(params.get("lag", max(1, window // 4))))
    if transform == "smooth":
        return _ema(signal, int(params.get("smooth", max(3, window // 3))))
    if transform == "rank":
        return _time_series_rank(signal, norm) - 0.5
    if transform == "vol_scaled":
        volatility = returns.rolling(norm, min_periods=_min_periods(norm)).std(ddof=0)
        return signal / volatility.replace(0, np.nan)
    if transform == "stability":
        volatility = signal.rolling(norm, min_periods=_min_periods(norm)).std(ddof=0)
        return signal / volatility.replace(0, np.nan)
    if transform == "confirm_volume":
        mean_volume = volume.rolling(norm, min_periods=_min_periods(norm)).mean()
        return signal * (volume / mean_volume)
    if transform == "compress":
        return np.tanh(signal)
    raise ValueError(f"未支持的内置因子变换: {transform}")


def compute_factor_values(ohlcv: pd.DataFrame, spec) -> pd.DataFrame | None:
    """根据因子 spec 从 OHLCV 数据中计算因子值

    目前支持 base 类型：
    - return: 日收益率
    - volume: 成交量
    - turnover: 换手率
    """
    df = ohlcv.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

    factor_id = getattr(spec, 'factor_id', '')
    base = getattr(spec, 'base', '') or ""
    params = getattr(spec, 'params', {}) or {}
    window = params.get("window", 5)

    # ---- Demo 因子特殊处理 ----
    if factor_id == "demo_future_leak":
        # 未来函数因子：使用未来数据（负窗口 = 向前看）
        df['ret'] = df['close'] / df['pre_close'] - 1
        df['factor_value'] = df.groupby('ts_code')['ret'].transform(
            lambda x: x.shift(-5).rolling(window=5, min_periods=3).mean()
        )
    elif factor_id == "demo_small_cap":
        # 小微盘暴露因子：因子值与市值高度相关
        if 'circ_mv' in df.columns:
            df['factor_value'] = -np.log(df['circ_mv'].replace(0, np.nan))
        elif 'total_mv' in df.columns:
            df['factor_value'] = -np.log(df['total_mv'].replace(0, np.nan))
        else:
            df['ret'] = df['close'] / df['pre_close'] - 1
            df['factor_value'] = df.groupby('ts_code')['ret'].transform(
                lambda x: x.rolling(window=5, min_periods=3).mean()
            )
    elif (getattr(spec, "source", "") in {"custom", "master_proxy"}
          and getattr(spec, "formula", None)):
        df['factor_value'] = _compute_formula_values(df, spec.formula)
    else:
        values = []
        for _, group in df.groupby("ts_code", sort=False):
            values.append(_compute_builtin_group(group, spec))
        df["factor_value"] = pd.concat(values).sort_index()

    # 保留窗口期产生的缺失值，供评估层相对完整股票池计算覆盖率。
    df.loc[np.isinf(df['factor_value']), 'factor_value'] = np.nan

    if df.empty or df['factor_value'].notna().sum() == 0:
        return None

    return df[['ts_code', 'trade_date', 'factor_value']].copy()


def load_aligned_data(session_state: dict, forward_period: int = 5) -> pd.DataFrame | None:
    """加载或计算对齐后的因子数据

    优先级：
    1. 从 session_state.aligned_data 获取
    2. 从 session_state.factor_df 获取
    3. 从 OHLCV 快照中计算因子值并对齐前瞻收益

    Parameters
    ----------
    session_state : dict
        Streamlit session_state 字典
    forward_period : int
        前瞻收益周期（交易日数）

    Returns
    -------
    pd.DataFrame | None
        对齐后的 DataFrame，含 ts_code, trade_date, factor_value, forward_return
    """
    factor_id = session_state.get("selected_factor_id")
    automatic_identity = _snapshot_data_identity()
    if automatic_identity is not None:
        session_state["data_snapshot_hash"] = automatic_identity
        session_state["automatic_data_snapshot_hash"] = automatic_identity
    context = {
        "factor_id": factor_id,
        "factor_context_hash": session_state.get("factor_context_hash"),
        "data_snapshot_hash": session_state.get("data_snapshot_hash"),
        "forward_period": int(forward_period),
    }

    # 1. 已有且属于当前因子/周期的对齐数据
    if (session_state.get("aligned_data") is not None
            and session_state.get("aligned_context") == context):
        return session_state["aligned_data"]
    if session_state.get("aligned_data") is not None:
        session_state.pop("aligned_data", None)
        session_state.pop("aligned_context", None)

    # 2. 从 factor_df 获取
    factor_df = session_state.get("factor_df")
    if factor_df is not None and 'factor_value' in factor_df.columns and 'forward_return' in factor_df.columns:
        session_state["aligned_data"] = factor_df
        session_state["aligned_context"] = context
        return factor_df

    # 3. 从 OHLCV 快照计算
    if factor_id is None:
        return None

    try:
        from engine.data_loader import get_ohlcv_data, get_basic_data
        from engine.data_aligner import align_factor_returns
        from engine.factor_loader import get_factor_by_id

        spec = session_state.get("selected_factor_spec")
        if spec is not None and getattr(spec, "factor_id", None) != factor_id:
            spec = None
        if spec is None:
            spec = get_factor_by_id(factor_id)
        if spec is None:
            return None

        # 缓存 OHLCV/basic 数据（大文件，避免重复加载 373MB+221MB）
        if "ohlcv_df" not in session_state or session_state["ohlcv_df"] is None:
            ohlcv = get_ohlcv_data()
            session_state["ohlcv_df"] = ohlcv
        else:
            ohlcv = session_state["ohlcv_df"]
        if "basic_df" not in session_state or session_state["basic_df"] is None:
            basic = get_basic_data()
            session_state["basic_df"] = basic
        else:
            basic = session_state["basic_df"]

        automatic_identity = _snapshot_data_identity()
        if automatic_identity is not None:
            session_state["data_snapshot_hash"] = automatic_identity
            session_state["automatic_data_snapshot_hash"] = automatic_identity
            context["data_snapshot_hash"] = automatic_identity

        # 上传因子值优先；否则根据 FactorSpec 计算。
        factor_df = session_state.get("factor_df")
        if factor_df is not None and 'factor_value' in factor_df.columns:
            factor_values = factor_df[['ts_code', 'trade_date', 'factor_value']].copy()
        else:
            factor_input = ohlcv
            extra_cols = [
                column for column in (
                    "total_mv", "circ_mv", "turnover_rate", "pe_ttm",
                    "net_profit_ttm", "cash_flow_ttm", "total_assets",
                    "net_assets", "total_liability", "net_profit_quarter",
                )
                if column in basic.columns and column not in ohlcv.columns
            ]
            if extra_cols:
                factor_input = ohlcv.merge(
                    basic[["ts_code", "trade_date"] + extra_cols],
                    on=["ts_code", "trade_date"],
                    how="left",
                )
            factor_values = compute_factor_values(factor_input, spec)
        if factor_values is None or factor_values.empty:
            return None

        # 对齐因子值与前瞻收益
        aligned = align_factor_returns(
            factor_values,
            ohlcv,
            basic,
            forward_period=forward_period,
        )

        if aligned is not None and not aligned.empty:
            # 合并 OHLCV/basic 列，供适用性地图等下游使用
            aligned['trade_date'] = pd.to_datetime(aligned['trade_date'])
            ohlcv['trade_date'] = pd.to_datetime(ohlcv['trade_date'])
            basic['trade_date'] = pd.to_datetime(basic['trade_date'])

            ohlcv_cols = [c for c in ['close', 'volume', 'turnover_rate'] if c in ohlcv.columns]
            basic_cols = [
                c for c in ['total_mv', 'circ_mv', 'turnover_rate', 'pe_ttm', 'pb']
                if c in basic.columns and c not in aligned.columns
            ]

            if ohlcv_cols:
                aligned = aligned.merge(
                    ohlcv[['ts_code', 'trade_date'] + ohlcv_cols],
                    on=['ts_code', 'trade_date'], how='left'
                )
            if basic_cols:
                aligned = aligned.merge(
                    basic[['ts_code', 'trade_date'] + basic_cols],
                    on=['ts_code', 'trade_date'], how='left'
                )

            session_state["aligned_data"] = aligned
            session_state["aligned_context"] = context
            session_state["selected_factor_name"] = spec.name_cn
            session_state["selected_factor_spec"] = spec
            return aligned

    except Exception as e:
        session_state["alignment_error"] = str(e)
        print(f"[load_aligned_data] 计算失败: {e}")

    return None
