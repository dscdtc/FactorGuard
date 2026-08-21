"""
数据对齐器模块
- 将因子值、收益标签和股票池对齐到统一时间截面
- 计算多周期前瞻收益（使用下一交易日开盘价，避免未来信息）
- 构建指定日期的可交易股票池
"""

import numpy as np
import pandas as pd
from config import DEFAULT_FORWARD_PERIOD


def compute_forward_returns(ohlcv_df, forward_periods=None):
    """计算多周期前瞻收益

    使用下一交易日开盘价作为买入价，避免未来信息。
    停牌日（volume=0 或 open=NaN）会被跳过，不计入前瞻周期。

    Parameters
    ----------
    ohlcv_df : pd.DataFrame
        包含列 ts_code, trade_date, open, volume
    forward_periods : list[int], optional
        前瞻周期列表（交易日数），默认 [1, 5, 10, 20]

    Returns
    -------
    pd.DataFrame
        包含原始列及 forward_return_1d, forward_return_5d,
        forward_return_10d, forward_return_20d 列
    """
    if forward_periods is None:
        forward_periods = [1, 5, 10, 20]

    df = ohlcv_df.copy()
    # 确保 trade_date 为 datetime 类型
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

    # 标记有效交易日（非停牌：volume > 0 且 open 不为空）
    df['_valid'] = (df['volume'] > 0) & df['open'].notna()

    for period in forward_periods:
        col_name = f'forward_return_{period}d'
        df[col_name] = np.nan

        # 按股票分组，在有效交易日子集上做向量化 shift
        for ts_code, group in df.groupby('ts_code'):
            # 仅取有效交易日子集
            valid = group[group['_valid']]
            if len(valid) <= period:
                continue

            # 在有效交易日子集上计算前瞻收益
            # forward_return = open[t+N] / open[t+1] - 1
            next_open = valid['open'].shift(-1)          # t+1 日开盘价（买入价）
            future_open = valid['open'].shift(-period)   # t+N 日开盘价（卖出价）

            forward_ret = future_open.values / next_open.values - 1

            # 合并回原 DataFrame
            df.loc[valid.index, col_name] = forward_ret

    # 清理临时列
    df = df.drop(columns=['_valid'])

    return df


def build_universe(ohlcv_df, basic_df, date, min_list_days=60):
    """构建指定日期的可交易股票池

    排除停牌股票（volume=0 或 close=NaN），
    并排除上市不足 min_list_days 个交易日的股票。

    Parameters
    ----------
    ohlcv_df : pd.DataFrame
        包含列 ts_code, trade_date, open, close, volume
    basic_df : pd.DataFrame
        包含列 ts_code, trade_date, total_mv（可选）
    date : str or datetime
        目标日期
    min_list_days : int
        最少上市交易日数，默认 60

    Returns
    -------
    list[str]
        该日期可交易的 ts_code 列表
    """
    date = pd.to_datetime(date)

    # 获取目标日期的数据
    day_data = ohlcv_df[ohlcv_df['trade_date'] == date]

    if day_data.empty:
        return []

    # 排除停牌股票（volume=0 或 close 为 NaN）
    active = day_data[(day_data['volume'] > 0) & day_data['close'].notna()]

    if active.empty:
        return []

    # 统计每只股票在目标日期（含）之前的历史交易日数量
    hist = ohlcv_df[ohlcv_df['trade_date'] <= date]
    hist_counts = hist.groupby('ts_code').size()

    # 排除上市不足 min_list_days 个交易日的股票
    seasoned = hist_counts[hist_counts >= min_list_days].index

    # 取交集：既不停牌、又满足上市时长要求
    active_codes = active[active['ts_code'].isin(seasoned)]['ts_code']

    return sorted(active_codes.unique().tolist())


def align_factor_returns(factor_df, ohlcv_df, basic_df, forward_period=None):
    """将因子值、收益标签和股票池对齐到统一时间截面

    处理流程：
    1. 筛选有效因子值（非空、非无限）
    2. 按 ts_code 和 trade_date 排序
    3. 计算前瞻收益（跳过停牌日，找不到则标记 NaN）
    4. 合并因子值和前瞻收益
    5. 按 historical_all_a 规则排除停牌股票

    Parameters
    ----------
    factor_df : pd.DataFrame
        包含列 ts_code, trade_date, factor_value
    ohlcv_df : pd.DataFrame
        包含列 ts_code, trade_date, open, close, volume
    basic_df : pd.DataFrame
        包含列 ts_code, trade_date, total_mv（可选）
    forward_period : int, optional
        前瞻收益周期（交易日数），默认使用 DEFAULT_FORWARD_PERIOD (5)

    Returns
    -------
    pd.DataFrame
        对齐后的 DataFrame，包含列：
        ts_code, trade_date, factor_value, forward_return
    """
    if forward_period is None:
        forward_period = DEFAULT_FORWARD_PERIOD

    # 1. 筛选有效因子值（非空、非无限）
    factor = factor_df.copy()
    factor['trade_date'] = pd.to_datetime(factor['trade_date'])
    factor = factor[factor['factor_value'].notna()]
    factor = factor[~np.isinf(factor['factor_value'])]

    if factor.empty:
        return pd.DataFrame(columns=['ts_code', 'trade_date', 'factor_value', 'forward_return'])

    # 2. 按 ts_code 和 trade_date 排序
    factor = factor.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

    # 3. 计算前瞻收益（只计算所需周期）
    ohlcv = ohlcv_df.copy()
    ohlcv['trade_date'] = pd.to_datetime(ohlcv['trade_date'])

    fwd_df = compute_forward_returns(ohlcv, forward_periods=[forward_period])
    fwd_col = f'forward_return_{forward_period}d'
    fwd_df = fwd_df[['ts_code', 'trade_date', fwd_col]].copy()
    fwd_df = fwd_df.rename(columns={fwd_col: 'forward_return'})

    # 4. 合并因子值和前瞻收益
    aligned = factor.merge(
        fwd_df,
        on=['ts_code', 'trade_date'],
        how='inner'
    )

    # 5. 按 historical_all_a 规则构建股票池
    #    MVP 中不做 ST 过滤，仅排除停牌（forward_return 为 NaN 的即为停牌）
    aligned = aligned.dropna(subset=['forward_return'])

    # 只保留需要的列，排序输出
    result = aligned[['ts_code', 'trade_date', 'factor_value', 'forward_return']].copy()
    result = result.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

    return result