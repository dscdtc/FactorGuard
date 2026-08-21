"""
因子值计算与对齐模块

从 OHLCV 数据中根据因子 spec 计算因子值，并对齐前瞻收益。
"""
import numpy as np
import pandas as pd


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
    elif "return" in base:
        df['ret'] = df['close'] / df['pre_close'] - 1
        df['factor_value'] = df.groupby('ts_code')['ret'].transform(
            lambda x: x.rolling(window=window, min_periods=max(3, window // 2)).mean()
        )
    elif "volume" in base:
        df['factor_value'] = df.groupby('ts_code')['volume'].transform(
            lambda x: x.rolling(window=window, min_periods=max(3, window // 2)).mean()
        )
    elif "turnover" in base:
        df['factor_value'] = df['amount'] / (df['circ_mv'] + 1e-12)
        df['factor_value'] = df.groupby('ts_code')['factor_value'].transform(
            lambda x: x.rolling(window=window, min_periods=max(3, window // 2)).mean()
        )
    else:
        df['ret'] = df['close'] / df['pre_close'] - 1
        df['factor_value'] = df.groupby('ts_code')['ret'].transform(
            lambda x: x.rolling(window=window, min_periods=max(3, window // 2)).mean()
        )

    df = df.dropna(subset=['factor_value'])
    df = df[~np.isinf(df['factor_value'])]

    if df.empty:
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
    # 1. 已有对齐数据
    if session_state.get("aligned_data") is not None:
        return session_state["aligned_data"]

    # 2. 从 factor_df 获取
    factor_df = session_state.get("factor_df")
    if factor_df is not None and 'factor_value' in factor_df.columns and 'forward_return' in factor_df.columns:
        session_state["aligned_data"] = factor_df
        return factor_df

    # 3. 从 OHLCV 快照计算
    factor_id = session_state.get("selected_factor_id")
    if factor_id is None:
        return None

    try:
        from engine.data_loader import get_ohlcv_data, get_basic_data
        from engine.data_aligner import align_factor_returns
        from engine.factor_loader import get_factor_by_id

        spec = None
        # Demo 因子特殊处理：从 session_state 获取 spec
        if factor_id.startswith("demo_"):
            spec = session_state.get("selected_factor_spec")
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

        # 根据因子 spec 计算因子值
        factor_values = compute_factor_values(ohlcv, spec)
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
            basic_cols = [c for c in ['total_mv', 'pe_ttm', 'pb'] if c in basic.columns]

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
            session_state["selected_factor_name"] = spec.name_cn
            session_state["selected_factor_spec"] = spec
            return aligned

    except Exception as e:
        import traceback
        print(f"[load_aligned_data] 计算失败: {e}")
        traceback.print_exc()

    return None