"""
传统评估引擎
- 计算完整的 Tear Sheet 指标（IC、RankIC、分组收益、换手率等）
- 按时间维度（年/季/月）聚合指标
"""
import numpy as np
import pandas as pd
from scipy import stats


def compute_daily_rank_ic(aligned_df: pd.DataFrame,
                          factor_col: str = 'factor_value',
                          return_col: str = 'forward_return') -> dict:
    """预计算每日 IC 和 RankIC，供下游函数复用

    Returns
    -------
    dict
        {
            "dates": list[str],          # 日期列表
            "ic": dict[date, float],     # 每日 IC
            "rank_ic": dict[date, float],# 每日 RankIC
            "direction": dict[date, float], # 每日方向一致率
            "coverage": dict[date, float],  # 每日覆盖率
        }
    """
    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.dropna(subset=[factor_col, return_col])
    df = df[~np.isinf(df[factor_col]) & ~np.isinf(df[return_col])]

    dates = sorted(df['trade_date'].unique())
    ic_dict = {}
    rank_ic_dict = {}
    direction_dict = {}
    coverage_dict = {}

    for date in dates:
        day = df[df['trade_date'] == date]
        if len(day) < 10:
            continue

        ic_val = day[factor_col].corr(day[return_col])
        if not np.isnan(ic_val):
            ic_dict[date] = ic_val

        rank_ic_val = day[factor_col].rank().corr(day[return_col].rank())
        if not np.isnan(rank_ic_val):
            rank_ic_dict[date] = rank_ic_val

        if len(day) >= 2:
            factor_sign = np.sign(day[factor_col] - day[factor_col].median())
            return_sign = np.sign(day[return_col] - day[return_col].median())
            direction_dict[date] = (factor_sign == return_sign).mean()

        total_stocks = len(day)
        valid_stocks = day[factor_col].notna().sum()
        coverage_dict[date] = valid_stocks / total_stocks if total_stocks > 0 else 0

    return {
        "dates": [str(d) for d in dates],
        "ic": ic_dict,
        "rank_ic": rank_ic_dict,
        "direction": direction_dict,
        "coverage": coverage_dict,
    }


def evaluate_factor(aligned_df: pd.DataFrame,
                    factor_col: str = 'factor_value',
                    return_col: str = 'forward_return',
                    daily_rank_ic: dict | None = None) -> dict:
    """计算完整的 Tear Sheet 指标

    Parameters
    ----------
    aligned_df : pd.DataFrame
        对齐后的 DataFrame，含 ts_code, trade_date, factor_value, forward_return
    factor_col : str
        因子值列名
    return_col : str
        前瞻收益列名

    Returns
    -------
    dict
        包含 ic_mean, ic_std, rank_ic_mean, rank_ic_std, icir, ic_t_stat,
        ic_p_value, direction_consistency, group_returns, cumulative_returns,
        turnover_top, turnover_bottom, coverage, rolling_ic, sample_count, date_range
    """
    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.dropna(subset=[factor_col, return_col])
    df = df[~np.isinf(df[factor_col]) & ~np.isinf(df[return_col])]

    if df.empty:
        return _empty_result()

    dates = sorted(df['trade_date'].unique())
    date_range_str = f"{pd.Timestamp(dates[0]).strftime('%Y-%m-%d')} ~ {pd.Timestamp(dates[-1]).strftime('%Y-%m-%d')}"
    sample_count = len(df)

    # 每日 IC —— 优先使用预计算结果
    if daily_rank_ic is not None:
        ic_list = [v for v in daily_rank_ic["ic"].values()]
        rank_ic_list = [v for v in daily_rank_ic["rank_ic"].values()]
        direction_list = [v for v in daily_rank_ic["direction"].values()]
        coverage_list = [v for v in daily_rank_ic["coverage"].values()]
    else:
        ic_list = []
        rank_ic_list = []
        direction_list = []
        coverage_list = []

    group_returns_dict = {0: [], 1: [], 2: [], 3: [], 4: []}
    top_turnover_list = []
    bottom_turnover_list = []

    for date in dates:
        day = df[df['trade_date'] == date].copy()
        if len(day) < 10:
            continue

        # 未预计算时自行计算 IC/RankIC/方向/覆盖率
        if daily_rank_ic is None:
            ic_val = day[factor_col].corr(day[return_col])
            if not np.isnan(ic_val):
                ic_list.append(ic_val)

            rank_ic_val = day[factor_col].rank().corr(day[return_col].rank())
            if not np.isnan(rank_ic_val):
                rank_ic_list.append(rank_ic_val)

            if len(day) >= 2:
                factor_sign = np.sign(day[factor_col] - day[factor_col].median())
                return_sign = np.sign(day[return_col] - day[return_col].median())
                direction_list.append((factor_sign == return_sign).mean())

            total_stocks = len(day)
            valid_stocks = day[factor_col].notna().sum()
            coverage_list.append(valid_stocks / total_stocks if total_stocks > 0 else 0)

        # 分组收益（始终需要计算，无法预计算复用）
        try:
            day['group'] = pd.qcut(day[factor_col].rank(method='first'), 5,
                                   labels=False, duplicates='drop')
            for g in range(5):
                if g in day['group'].values:
                    group_returns_dict[g].append(day.loc[day['group'] == g, return_col].mean())
        except Exception:
            pass

        # 换手率（Top/Bottom 分组）
        if 'group' in day.columns:
            top_g = day[day['group'] == 4]
            bottom_g = day[day['group'] == 0]
            if len(top_g) > 0:
                top_turnover_list.append(1.0 / len(top_g))
            if len(bottom_g) > 0:
                bottom_turnover_list.append(1.0 / len(bottom_g))

    # 汇总指标
    ic_arr = np.array(ic_list)
    rank_ic_arr = np.array(rank_ic_list)

    ic_mean = float(np.mean(ic_arr)) if len(ic_arr) > 0 else 0.0
    ic_std = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 0.0
    rank_ic_mean = float(np.mean(rank_ic_arr)) if len(rank_ic_arr) > 0 else 0.0
    rank_ic_std = float(np.std(rank_ic_arr, ddof=1)) if len(rank_ic_arr) > 1 else 0.0

    # ICIR = ic_mean / ic_std * sqrt(252)
    icir = (ic_mean / ic_std * np.sqrt(252)) if ic_std > 0 else 0.0

    # IC t 统计量
    ic_t_stat = float(ic_mean / (ic_std / np.sqrt(len(ic_arr)))) if ic_std > 0 and len(ic_arr) > 1 else 0.0
    ic_p_value = float(2 * stats.t.sf(abs(ic_t_stat), df=len(ic_arr) - 1)) if len(ic_arr) > 1 else 1.0

    # 方向一致率
    direction_consistency = float(np.mean(direction_list)) if direction_list else 0.0

    # 分组平均收益
    group_returns = []
    for g in range(5):
        arr = group_returns_dict.get(g, [])
        group_returns.append(float(np.mean(arr)) if arr else 0.0)

    # 累计收益
    cumulative_returns = {}
    for g in range(5):
        arr = group_returns_dict.get(g, [])
        cumulative_returns[f"G{g+1}"] = [float(x) for x in np.cumsum(arr).tolist()] if arr else []

    # 换手率
    turnover_top = float(np.mean(top_turnover_list)) if top_turnover_list else 0.0
    turnover_bottom = float(np.mean(bottom_turnover_list)) if bottom_turnover_list else 0.0

    # 覆盖率
    coverage = float(np.mean(coverage_list)) if coverage_list else 0.0

    # 滚动 RankIC（63 日滚动窗口，min_periods=30）
    rolling_ic_df = _compute_rolling_rank_ic(df, factor_col, return_col, dates)

    return {
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "rank_ic_mean": rank_ic_mean,
        "rank_ic_std": rank_ic_std,
        "icir": icir,
        "ic_t_stat": ic_t_stat,
        "ic_p_value": ic_p_value,
        "direction_consistency": direction_consistency,
        "group_returns": group_returns,
        "cumulative_returns": cumulative_returns,
        "turnover_top": turnover_top,
        "turnover_bottom": turnover_bottom,
        "coverage": coverage,
        "rolling_ic": rolling_ic_df,
        "sample_count": sample_count,
        "date_range": date_range_str,
    }


def evaluate_by_time_dimension(aligned_df: pd.DataFrame,
                               dim: str = 'year',
                               daily_rank_ic: dict | None = None) -> pd.DataFrame:
    """按年/季/月聚合指标

    Parameters
    ----------
    aligned_df : pd.DataFrame
        对齐后的 DataFrame
    dim : str
        时间维度: 'year', 'quarter', 'month'
    daily_rank_ic : dict, optional
        预计算的每日 RankIC 数据，传入时按 period 分组过滤后复用

    Returns
    -------
    pd.DataFrame
        按时间维度分组的指标 DataFrame
    """
    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])

    if dim == 'year':
        df['_period'] = df['trade_date'].dt.year
    elif dim == 'quarter':
        df['_period'] = df['trade_date'].dt.to_period('Q').astype(str)
    elif dim == 'month':
        df['_period'] = df['trade_date'].dt.to_period('M').astype(str)
    else:
        raise ValueError(f"dim must be 'year', 'quarter', or 'month', got '{dim}'")

    rows = []
    for period, group in df.groupby('_period'):
        # 为当前 period 过滤预计算结果
        period_daily = None
        if daily_rank_ic is not None:
            group_dates = set(pd.to_datetime(group['trade_date'].unique()))
            period_daily = {
                "ic": {d: v for d, v in daily_rank_ic["ic"].items() if pd.Timestamp(d) in group_dates},
                "rank_ic": {d: v for d, v in daily_rank_ic["rank_ic"].items() if pd.Timestamp(d) in group_dates},
                "direction": {d: v for d, v in daily_rank_ic["direction"].items() if pd.Timestamp(d) in group_dates},
                "coverage": {d: v for d, v in daily_rank_ic["coverage"].items() if pd.Timestamp(d) in group_dates},
            }
        result = evaluate_factor(group, factor_col='factor_value', return_col='forward_return',
                                 daily_rank_ic=period_daily)
        rows.append({
            'period': period,
            'ic_mean': result['ic_mean'],
            'rank_ic_mean': result['rank_ic_mean'],
            'icir': result['icir'],
            'direction_consistency': result['direction_consistency'],
            'coverage': result['coverage'],
            'sample_count': result['sample_count'],
        })

    return pd.DataFrame(rows)


def _compute_rolling_rank_ic(df: pd.DataFrame,
                             factor_col: str,
                             return_col: str,
                             dates: list) -> pd.DataFrame:
    """计算滚动 RankIC（63 日滚动窗口，min_periods=30）"""
    daily_rank_ic = {}
    for date in dates:
        day = df[df['trade_date'] == date]
        if len(day) < 10:
            continue
        ric = day[factor_col].rank().corr(day[return_col].rank())
        if not np.isnan(ric):
            daily_rank_ic[pd.Timestamp(date)] = ric

    if not daily_rank_ic:
        return pd.DataFrame(columns=['date', 'rolling_rank_ic'])

    series = pd.Series(daily_rank_ic).sort_index()
    rolling = series.rolling(window=63, min_periods=30).mean().dropna()

    result = pd.DataFrame({
        'date': rolling.index,
        'rolling_rank_ic': rolling.values
    }).reset_index(drop=True)

    return result


def _empty_result() -> dict:
    """返回空的评估结果"""
    return {
        "ic_mean": 0.0,
        "ic_std": 0.0,
        "rank_ic_mean": 0.0,
        "rank_ic_std": 0.0,
        "icir": 0.0,
        "ic_t_stat": 0.0,
        "ic_p_value": 1.0,
        "direction_consistency": 0.0,
        "group_returns": [0.0] * 5,
        "cumulative_returns": {f"G{i+1}": [] for i in range(5)},
        "turnover_top": 0.0,
        "turnover_bottom": 0.0,
        "coverage": 0.0,
        "rolling_ic": pd.DataFrame(columns=['date', 'rolling_rank_ic']),
        "sample_count": 0,
        "date_range": "无数据",
    }


def compute_factor_distribution(aligned_df: pd.DataFrame,
                                 factor_col: str = 'factor_value') -> dict:
    """计算因子值分布统计

    Returns
    -------
    dict with factor_values, coverage_series (dates, coverage)
    """
    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.dropna(subset=[factor_col])

    factor_values = df[factor_col].values.tolist()

    # 每日覆盖率
    coverage_series = df.groupby('trade_date').apply(
        lambda g: g[factor_col].notna().sum() / len(g)
    ).reset_index()
    coverage_series.columns = ['date', 'coverage']

    return {
        'factor_values': factor_values,
        'coverage_dates': coverage_series['date'].tolist(),
        'coverage_values': coverage_series['coverage'].tolist(),
    }


def compute_ic_decay(aligned_df: pd.DataFrame,
                     periods: list = [1, 5, 10, 20],
                     factor_col: str = 'factor_value',
                     ohlcv_df: pd.DataFrame | None = None) -> dict:
    """计算不同预测周期的 IC 衰减

    Parameters
    ----------
    periods : list
        预测周期列表（交易日）
    ohlcv_df : pd.DataFrame, optional
        OHLCV 数据，用于计算不同周期的前瞻收益。若为 None 则返回空结果。

    Returns
    -------
    dict with periods and rank_ic_values
    """
    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])

    if ohlcv_df is None or ohlcv_df.empty:
        return {
            'periods': [str(p) for p in periods],
            'rank_ic_values': [0.0] * len(periods),
        }

    # 从 OHLCV 获取 close 价格
    ohlcv = ohlcv_df.copy()
    ohlcv['trade_date'] = pd.to_datetime(ohlcv['trade_date'])
    if 'close' not in ohlcv.columns:
        return {
            'periods': [str(p) for p in periods],
            'rank_ic_values': [0.0] * len(periods),
        }

    # 合并 close 价格（若 aligned_df 已有 close 列则先移除，避免 merge 冲突）
    if 'close' in df.columns:
        df = df.drop(columns=['close'])
    df = df.merge(
        ohlcv[['ts_code', 'trade_date', 'close']],
        on=['ts_code', 'trade_date'],
        how='left'
    )
    df = df.sort_values(['ts_code', 'trade_date'])

    results = {}
    for p in periods:
        # 计算 p 日前瞻收益
        df_temp = df.copy()
        df_temp['forward_return_p'] = df_temp.groupby('ts_code')['close'].transform(
            lambda x: x.shift(-p) / x - 1
        )
        df_temp = df_temp.dropna(subset=['forward_return_p', factor_col])

        if df_temp.empty:
            results[p] = 0.0
            continue

        # 计算每日 RankIC
        rank_ic_list = []
        for date in sorted(df_temp['trade_date'].unique()):
            day = df_temp[df_temp['trade_date'] == date]
            if len(day) < 10:
                continue
            ric = day[factor_col].rank().corr(day['forward_return_p'].rank())
            if not np.isnan(ric):
                rank_ic_list.append(ric)

        results[p] = float(np.mean(rank_ic_list)) if rank_ic_list else 0.0

    return {
        'periods': [str(p) for p in periods],
        'rank_ic_values': [results[p] for p in periods],
    }


def compute_factor_autocorr(aligned_df: pd.DataFrame,
                             factor_col: str = 'factor_value',
                             max_lag: int = 10) -> dict:
    """计算因子自相关（跨股票均值）

    Returns
    -------
    dict with lags and autocorr_values
    """
    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values(['ts_code', 'trade_date'])

    autocorr_by_stock = {}
    for code, group in df.groupby('ts_code'):
        if len(group) < max_lag + 5:
            continue
        vals = group[factor_col].dropna().values
        if len(vals) < max_lag + 5:
            continue
        autocorr_by_stock[code] = vals

    if not autocorr_by_stock:
        return {'lags': list(range(1, max_lag + 1)), 'autocorr_values': [0.0] * max_lag}

    # 计算每只股票的自相关，然后取截面均值
    ac_values = []
    for lag in range(1, max_lag + 1):
        lag_ac = []
        for vals in autocorr_by_stock.values():
            if len(vals) > lag:
                ac = np.corrcoef(vals[:-lag], vals[lag:])[0, 1]
                if not np.isnan(ac):
                    lag_ac.append(ac)
        ac_values.append(float(np.mean(lag_ac)) if lag_ac else 0.0)

    return {
        'lags': list(range(1, max_lag + 1)),
        'autocorr_values': ac_values,
    }


def compute_neutralized_compare(aligned_df: pd.DataFrame,
                                 ohlcv_df: pd.DataFrame,
                                 factor_col: str = 'factor_value') -> dict:
    """市值中性化对比：原始因子 vs 市值中性化因子

    Returns
    -------
    dict with original_rank_ic, neutralized_rank_ic
    """
    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])

    # 为 neutralization 获取市值数据
    ohlcv = ohlcv_df.copy()
    ohlcv['trade_date'] = pd.to_datetime(ohlcv['trade_date'])

    # 合并市值
    if 'total_mv' in ohlcv.columns:
        mv_col = 'total_mv'
    elif 'circ_mv' in ohlcv.columns:
        mv_col = 'circ_mv'
    else:
        return None

    df = df.merge(
        ohlcv[['ts_code', 'trade_date', mv_col]],
        on=['ts_code', 'trade_date'],
        how='left',
        suffixes=('', '_mv')
    )
    df = df.dropna(subset=[mv_col, factor_col])

    if df.empty:
        return None

    # 中性化：每日横截面回归 factor_value ~ log(mv)，取残差
    neutralized = []
    for date in sorted(df['trade_date'].unique()):
        day = df[df['trade_date'] == date].copy()
        if len(day) < 30:
            continue
        day[mv_col] = day[mv_col].replace(0, np.nan)
        day = day.dropna(subset=[mv_col])
        if len(day) < 30:
            continue
        try:
            x = np.log(day[mv_col].values)
            y = day[factor_col].values
            # 简单 OLS
            x_mean = np.mean(x)
            y_mean = np.mean(y)
            beta = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2)
            alpha = y_mean - beta * x_mean
            residual = y - (alpha + beta * x)
            day['factor_neut'] = residual
            neutralized.append(day[['ts_code', 'trade_date', factor_col, 'factor_neut', 'forward_return']])
        except Exception:
            continue

    if not neutralized:
        return None

    neut_df = pd.concat(neutralized, ignore_index=True)

    # 计算原始 RankIC
    orig_ric = _compute_daily_rank_ic(neut_df, factor_col)
    neut_ric = _compute_daily_rank_ic(neut_df, 'factor_neut')

    return {
        'original_rank_ic_mean': float(np.mean(orig_ric)) if orig_ric else 0.0,
        'neutralized_rank_ic_mean': float(np.mean(neut_ric)) if neut_ric else 0.0,
    }


def _compute_daily_rank_ic(df: pd.DataFrame, factor_col: str) -> list:
    """计算每日 RankIC"""
    ric_list = []
    for date in sorted(df['trade_date'].unique()):
        day = df[df['trade_date'] == date]
        if len(day) < 10:
            continue
        ric = day[factor_col].rank().corr(day['forward_return'].rank())
        if not np.isnan(ric):
            ric_list.append(ric)
    return ric_list