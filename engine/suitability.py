"""
适用性地图计算引擎

功能：
- compute_suitability_map: 主函数，计算二维适用性矩阵
- get_dimension_values: 辅助函数，计算维度分组值
"""

import numpy as np
import pandas as pd


def get_dimension_values(df: pd.DataFrame, dim: str) -> pd.Series:
    """根据维度名称计算分组标签，返回与 df 等长的 Series。

    Parameters
    ----------
    df : pd.DataFrame
        对齐后的因子数据，需包含 trade_date, factor_value, forward_return
        以及对应维度所需的列。
    dim : str
        维度名称，支持：
        - 'market_cap'    : 市值 → 按 total_mv 分位数分为 大盘/中盘/小盘/微盘
        - 'volatility'    : 波动率 → 按 20日波动率分位数分为 低/中/高/极高波动
        - 'style'         : 风格 → 按 PE/PB 综合分位数分为 成长/平衡/价值
        - 'liquidity'     : 流动性 → 按换手率分位数分为 低/中/高流动性
        - 'time'          : 时间 → 按自然年分段

    Returns
    -------
    pd.Series
        与 df 等长的分组标签
    """
    if dim == 'market_cap':
        return _get_market_cap_groups(df)
    elif dim == 'volatility':
        return _get_volatility_groups(df)
    elif dim == 'style':
        return _get_style_groups(df)
    elif dim == 'liquidity':
        return _get_liquidity_groups(df)
    elif dim == 'time':
        return _get_time_groups(df)
    else:
        raise ValueError(f"不支持的维度: {dim}")


def _get_market_cap_groups(df: pd.DataFrame) -> pd.Series:
    """市值分组：大盘/中盘/小盘/微盘"""
    if 'total_mv' not in df.columns:
        return pd.Series('未知', index=df.index)
    mv = df['total_mv']
    labels = ['微盘', '小盘', '中盘', '大盘']
    return pd.qcut(mv, q=4, labels=labels, duplicates='drop').astype(str)


def _get_volatility_groups(df: pd.DataFrame) -> pd.Series:
    """波动率分组：低/中/高/极高波动"""
    col = None
    if 'volatility_20d' in df.columns:
        col = 'volatility_20d'
    elif 'realized_vol' in df.columns:
        col = 'realized_vol'
    elif 'close' in df.columns and 'ts_code' in df.columns:
        # 动态计算 20日波动率（日收益率标准差）
        df = df.copy()
        df['_ret'] = df.groupby('ts_code')['close'].pct_change()
        vol = df.groupby('ts_code')['_ret'].rolling(20, min_periods=5).std().reset_index(level=0, drop=True)
        df['_vol_20d'] = vol
        col = '_vol_20d'
    else:
        return pd.Series('未知', index=df.index)

    valid = df[col].notna() & (df[col] > 0)
    result = pd.Series('未知', index=df.index)
    if valid.sum() < 4:
        return result
    result[valid] = pd.qcut(
        df.loc[valid, col], q=4,
        labels=['低波动', '中波动', '高波动', '极高波动'],
        duplicates='drop'
    ).astype(str)
    return result


def _get_style_groups(df: pd.DataFrame) -> pd.Series:
    """风格分组：成长/平衡/价值（基于 PE/PB 综合）"""
    has_pe = 'pe_ttm' in df.columns
    has_pb = 'pb' in df.columns

    if not has_pe and not has_pb:
        return pd.Series('未知', index=df.index)

    # 对 PE/PB 分别排名后取平均（PE 越低越偏价值端）
    ranks = pd.DataFrame(index=df.index)
    if has_pe:
        pe_valid = df['pe_ttm'].notna() & (df['pe_ttm'] > 0)
        ranks['pe_rank'] = np.nan
        ranks.loc[pe_valid, 'pe_rank'] = df.loc[pe_valid, 'pe_ttm'].rank(pct=True)
    if has_pb:
        pb_valid = df['pb'].notna() & (df['pb'] > 0)
        ranks['pb_rank'] = np.nan
        ranks.loc[pb_valid, 'pb_rank'] = df.loc[pb_valid, 'pb'].rank(pct=True)

    composite = ranks.mean(axis=1, skipna=True)
    valid = composite.notna()
    result = pd.Series('未知', index=df.index)
    if valid.sum() < 3:
        return result

    # 低分位 = 低估值/价值，高分位 = 高估值/成长
    result[valid] = pd.qcut(
        composite[valid], q=3,
        labels=['价值', '平衡', '成长'],
        duplicates='drop'
    ).astype(str)
    return result


def _get_liquidity_groups(df: pd.DataFrame) -> pd.Series:
    """流动性分组：低/中/高流动性（按换手率）"""
    col = None
    if 'turnover_rate' in df.columns:
        col = 'turnover_rate'
    elif 'volume' in df.columns and 'total_mv' in df.columns:
        # 用 volume / total_mv 近似换手率
        df = df.copy()
        df['_turnover'] = df['volume'] / df['total_mv']
        col = '_turnover'
    else:
        return pd.Series('未知', index=df.index)

    valid = df[col].notna() & (df[col] > 0)
    result = pd.Series('未知', index=df.index)
    if valid.sum() < 3:
        return result
    result[valid] = pd.qcut(
        df.loc[valid, col], q=3,
        labels=['低流动性', '中流动性', '高流动性'],
        duplicates='drop'
    ).astype(str)
    return result


def _get_time_groups(df: pd.DataFrame) -> pd.Series:
    """时间分组：按自然年分段"""
    if 'trade_date' not in df.columns:
        return pd.Series('未知', index=df.index)
    dates = pd.to_datetime(df['trade_date'])
    return dates.dt.year.astype(str)


# ============================================================
# 主函数
# ============================================================

def compute_suitability_map(
    aligned_df: pd.DataFrame,
    dim1: str = 'market_cap',
    dim2: str = 'volatility',
) -> dict:
    """计算因子适用性二维矩阵。

    对每个 (dim1, dim2) 子组，计算 RankIC、样本数、证据等级和方向翻转标记。

    Parameters
    ----------
    aligned_df : pd.DataFrame
        对齐后的因子数据，需包含 ts_code, trade_date, factor_value, forward_return
        以及对应维度所需字段。
    dim1 : str
        主维度（行），默认 'market_cap'
    dim2 : str
        次维度（列），默认 'volatility'

    Returns
    -------
    dict
        {
            "matrix": list[list[dict]],
            "dim1_name": str,
            "dim2_name": str,
            "dim1_values": list[str],
            "dim2_values": list[str],
            "overall_assessment": str,
        }
    """
    # 维度映射
    dim_labels = {
        'market_cap': '市值',
        'volatility': '波动率',
        'style': '成长价值',
        'liquidity': '流动性',
        'time': '时间',
    }

    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])

    # 计算总体 RankIC 符号
    overall_rank_ic = _compute_rank_ic(df['factor_value'], df['forward_return'])

    # 计算各维度分组值
    df['_dim1'] = get_dimension_values(df, dim1)
    df['_dim2'] = get_dimension_values(df, dim2)

    # 排除未知分组
    df_valid = df[(df['_dim1'] != '未知') & (df['_dim2'] != '未知')]

    dim1_values = sorted(df_valid['_dim1'].unique().tolist())
    dim2_values = sorted(df_valid['_dim2'].unique().tolist())

    # 构建矩阵
    matrix = []
    for d1 in dim1_values:
        row = []
        for d2 in dim2_values:
            sub = df_valid[(df_valid['_dim1'] == d1) & (df_valid['_dim2'] == d2)]
            cell = _compute_cell(sub, overall_rank_ic)
            row.append(cell)
        matrix.append(row)

    # 总体评估
    overall_assessment = _build_overall_assessment(
        matrix, dim1_values, dim2_values,
        dim_labels.get(dim1, dim1), dim_labels.get(dim2, dim2)
    )

    return {
        "matrix": matrix,
        "dim1_name": dim_labels.get(dim1, dim1),
        "dim2_name": dim_labels.get(dim2, dim2),
        "dim1_values": dim1_values,
        "dim2_values": dim2_values,
        "overall_assessment": overall_assessment,
    }


def _compute_rank_ic(factor_values: pd.Series, forward_returns: pd.Series) -> float:
    """计算 RankIC (Spearman 相关系数)"""
    valid = factor_values.notna() & forward_returns.notna()
    if valid.sum() < 3:
        return 0.0
    return factor_values[valid].rank().corr(forward_returns[valid].rank())


def _compute_cell(sub_df: pd.DataFrame, overall_rank_ic: float) -> dict:
    """计算单个单元格的指标"""
    n = len(sub_df)
    if n == 0:
        return {
            "rank_ic": 0.0,
            "sample_count": 0,
            "evidence_level": "na",
            "direction_flipped": False,
        }

    rank_ic = _compute_rank_ic(sub_df['factor_value'], sub_df['forward_return'])

    if n >= 252:
        evidence_level = "good"
    elif n >= 60:
        evidence_level = "mid"
    else:
        evidence_level = "weak"

    direction_flipped = False
    if overall_rank_ic != 0 and rank_ic != 0:
        direction_flipped = (overall_rank_ic * rank_ic) < 0

    return {
        "rank_ic": round(rank_ic, 6),
        "sample_count": n,
        "evidence_level": evidence_level,
        "direction_flipped": direction_flipped,
    }


def _build_overall_assessment(
    matrix: list[list[dict]],
    dim1_values: list[str],
    dim2_values: list[str],
    dim1_name: str,
    dim2_name: str,
) -> str:
    """生成总体评估文字"""
    total_cells = len(dim1_values) * len(dim2_values)
    if total_cells == 0:
        return "样本数据不足，无法生成适用性评估。"

    good_count = sum(1 for row in matrix for c in row if c['evidence_level'] == 'good')
    mid_count = sum(1 for row in matrix for c in row if c['evidence_level'] == 'mid')
    weak_count = sum(1 for row in matrix for c in row if c['evidence_level'] == 'weak')
    na_count = sum(1 for row in matrix for c in row if c['evidence_level'] == 'na')
    flipped_count = sum(1 for row in matrix for c in row if c['direction_flipped'])

    parts = []

    # 证据覆盖度
    covered = total_cells - na_count
    if covered == total_cells:
        parts.append(f"覆盖全部 {dim1_name}×{dim2_name} 组合，")
    else:
        parts.append(f"覆盖 {covered}/{total_cells} 个 {dim1_name}×{dim2_name} 组合，")

    # 证据等级分布
    if good_count >= total_cells * 0.5:
        parts.append(f"证据充足（{good_count} 个单元格样本量≥252），")
    elif good_count > 0:
        parts.append(f"部分单元格证据充足（{good_count} 个），")
    if mid_count > 0:
        parts.append(f"{mid_count} 个单元格样本量中等，")
    if weak_count > 0:
        parts.append(f"{weak_count} 个单元格样本量偏少，")

    # 方向翻转
    if flipped_count == 0:
        parts.append("无方向翻转，因子方向一致性良好。")
    elif flipped_count <= 2:
        parts.append(f"{flipped_count} 个单元格方向翻转，需关注局部失效。")
    else:
        parts.append(f"{flipped_count} 个单元格方向翻转，因子适用性存在显著分化。")

    # 最优/最差场景
    best_cell = None
    worst_cell = None
    for i, row in enumerate(matrix):
        for j, c in enumerate(row):
            if c['sample_count'] == 0:
                continue
            if best_cell is None or c['rank_ic'] > best_cell[2]:
                best_cell = (i, j, c['rank_ic'])
            if worst_cell is None or c['rank_ic'] < worst_cell[2]:
                worst_cell = (i, j, c['rank_ic'])

    if best_cell and worst_cell:
        bi, bj, bv = best_cell
        wi, wj, wv = worst_cell
        parts.append(
            f" 最佳场景：{dim1_name}={dim1_values[bi]} × {dim2_name}={dim2_values[bj]} (IC={bv:.4f})；"
            f"最差场景：{dim1_name}={dim1_values[wi]} × {dim2_name}={dim2_values[wj]} (IC={wv:.4f})。"
        )

    return ''.join(parts)