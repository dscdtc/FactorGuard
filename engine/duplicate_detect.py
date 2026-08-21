"""
重复检测引擎 - 三层因子重复检测

1. 公式结构相似度 - 基于 formula 字符串的相似度
2. 横截面暴露相关性 - 各交易日因子值 Spearman 秩相关均值
3. 因子收益相关性 - Top-Bottom 分组收益序列的 Pearson 相关
"""

import difflib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr

from engine.formula_parser import FormulaParser


def _formula_similarity(factor1_spec, factor2_spec) -> dict:
    """计算公式结构相似度"""
    f1 = (factor1_spec.formula or "").strip()
    f2 = (factor2_spec.formula or "").strip()

    if not f1 or not f2:
        return {
            "score": 0.0,
            "level": "low",
            "details": "至少一个因子缺少公式定义，无法比较公式结构。"
        }

    # 尝试解析两个公式
    parser = FormulaParser()
    r1 = parser.parse(f1)
    r2 = parser.parse(f2)

    if r1.valid and r2.valid:
        # 基础字段和函数比较
        fields1 = set(r1.used_fields)
        fields2 = set(r2.used_fields)
        funcs1 = set(r1.used_functions)
        funcs2 = set(r2.used_functions)

        field_overlap = len(fields1 & fields2) / max(len(fields1 | fields2), 1)
        func_overlap = len(funcs1 & funcs2) / max(len(funcs1 | funcs2), 1)

        if f1 == f2:
            score = 1.0
            level = "high"
            details = "两个公式完全相同。"
        elif field_overlap > 0.8 and func_overlap > 0.8:
            score = 0.8
            level = "medium"
            details = f"公式结构高度相似（字段重叠 {field_overlap:.0%}，函数重叠 {func_overlap:.0%}）。"
        elif field_overlap > 0.5 or func_overlap > 0.5:
            score = 0.5
            level = "medium"
            details = f"公式存在部分重叠（字段重叠 {field_overlap:.0%}，函数重叠 {func_overlap:.0%}）。"
        else:
            score = 0.0
            level = "low"
            details = f"公式结构差异较大（字段重叠 {field_overlap:.0%}，函数重叠 {func_overlap:.0%}）。"
    else:
        # 解析失败时回退到字符串相似度
        score = difflib.SequenceMatcher(None, f1, f2).ratio()
        if score > 0.9:
            level = "high"
            details = "公式字符串高度相似。"
        elif score > 0.6:
            level = "medium"
            details = "公式字符串存在中等相似度。"
        else:
            level = "low"
            details = "公式字符串相似度较低。"

    return {"score": round(score, 4), "level": level, "details": details}


def _exposure_correlation(factor1_df, factor2_df) -> dict:
    """计算横截面暴露相关性（Spearman 秩相关）"""
    if factor1_df.empty or factor2_df.empty:
        return {
            "score": 0.0,
            "level": "low",
            "details": "数据不足，无法计算暴露相关性。"
        }

    f1 = factor1_df[['ts_code', 'trade_date', 'factor_value']].copy()
    f2 = factor2_df[['ts_code', 'trade_date', 'factor_value']].copy()
    f1 = f1.rename(columns={'factor_value': 'fv1'})
    f2 = f2.rename(columns={'factor_value': 'fv2'})

    merged = f1.merge(f2, on=['ts_code', 'trade_date'], how='inner')

    if merged.empty:
        return {
            "score": 0.0,
            "level": "low",
            "details": "两个因子没有重叠的交易日和股票，无法计算暴露相关性。"
        }

    dates = sorted(merged['trade_date'].unique())
    cors = []
    for d in dates:
        day_data = merged[merged['trade_date'] == d]
        if len(day_data) < 10:
            continue
        corr, _ = spearmanr(day_data['fv1'], day_data['fv2'], nan_policy='omit')
        if not np.isnan(corr):
            cors.append(corr)

    if not cors:
        return {
            "score": 0.0,
            "level": "low",
            "details": "有效交易日不足，无法计算暴露相关性。"
        }

    mean_corr = float(np.mean(cors))
    score = abs(mean_corr)

    if score > 0.85:
        level = "high"
    elif score > 0.70:
        level = "medium"
    else:
        level = "low"

    details = (
        f"基于 {len(cors)} 个交易日的横截面 Spearman 秩相关，"
        f"均值 = {mean_corr:.4f}，标准差 = {np.std(cors):.4f}。"
    )

    return {"score": round(score, 4), "level": level, "details": details}


def _return_correlation(factor1_df, factor2_df) -> dict:
    """计算因子收益相关性（Top-Bottom 分组收益序列 Pearson 相关）"""
    if factor1_df.empty or factor2_df.empty:
        return {
            "score": 0.0,
            "level": "low",
            "details": "数据不足，无法计算收益相关性。"
        }

    def _top_bottom_return(df):
        """计算每个交易日的 Top-Bottom 收益差"""
        records = []
        for d, group in df.groupby('trade_date'):
            group = group.dropna(subset=['factor_value', 'forward_return'])
            if len(group) < 20:
                continue
            n = max(int(len(group) * 0.2), 1)
            top = group.nlargest(n, 'factor_value')
            bot = group.nsmallest(n, 'factor_value')
            top_ret = top['forward_return'].mean()
            bot_ret = bot['forward_return'].mean()
            records.append({
                'trade_date': d,
                'top_bottom_return': top_ret - bot_ret
            })
        return pd.DataFrame(records)

    ret1 = _top_bottom_return(factor1_df)
    ret2 = _top_bottom_return(factor2_df)

    if ret1.empty or ret2.empty:
        return {
            "score": 0.0,
            "level": "low",
            "details": "有效交易日不足，无法计算收益相关性。"
        }

    merged = ret1.merge(ret2, on='trade_date', how='inner',
                        suffixes=('_1', '_2'))
    if len(merged) < 10:
        return {
            "score": 0.0,
            "level": "low",
            "details": f"重叠交易日仅 {len(merged)} 个（需至少 10 个），无法可靠计算收益相关性。"
        }

    corr, pval = pearsonr(merged['top_bottom_return_1'],
                          merged['top_bottom_return_2'])
    score = abs(corr) if not np.isnan(corr) else 0.0

    if score > 0.80:
        level = "high"
    elif score > 0.65:
        level = "medium"
    else:
        level = "low"

    details = (
        f"基于 {len(merged)} 个重叠交易日的 Top-Bottom 分组收益序列，"
        f"Pearson r = {corr:.4f}（p = {pval:.4f}）。"
    )

    return {"score": round(score, 4), "level": level, "details": details}


def _overall_verdict(formula, exposure, ret) -> tuple[str, str]:
    """综合判定"""
    exp_score = exposure["score"]
    ret_score = ret["score"]

    if exp_score > 0.85 and ret_score > 0.80:
        verdict = "高度相似"
        summary = (
            f"两个因子在横截面暴露（Spearman ρ = {exp_score:.4f}）和"
            f"因子收益（Pearson r = {ret_score:.4f}）上均表现出高度一致性，"
            f"极可能为重复因子。"
        )
    elif exp_score > 0.70 and ret_score > 0.65:
        verdict = "中等相似"
        summary = (
            f"两个因子在横截面暴露（Spearman ρ = {exp_score:.4f}）和"
            f"因子收益（Pearson r = {ret_score:.4f}）上表现出中等一致性，"
            f"存在一定重叠但仍有差异。"
        )
    else:
        verdict = "不相似"
        summary = (
            f"两个因子在横截面暴露（Spearman ρ = {exp_score:.4f}）和"
            f"因子收益（Pearson r = {ret_score:.4f}）上均未表现出显著一致性，"
            f"可视为独立因子。"
        )

    if formula["score"] > 0.8:
        summary += f" 公式层面相似度较高（{formula['score']:.4f}）。"
    elif formula["score"] > 0.5:
        summary += f" 公式层面存在中等相似度（{formula['score']:.4f}）。"
    else:
        summary += f" 公式层面相似度较低（{formula['score']:.4f}）。"

    return verdict, summary


def detect_duplicates(factor1_df, factor2_df, factor1_spec, factor2_spec) -> dict:
    """执行三层因子重复检测

    Parameters
    ----------
    factor1_df : pd.DataFrame
        因子1 的对齐数据（含 ts_code, trade_date, factor_value, forward_return）
    factor2_df : pd.DataFrame
        因子2 的对齐数据
    factor1_spec : FactorSpec
    factor2_spec : FactorSpec

    Returns
    -------
    dict
        包含 formula_similarity, exposure_correlation, return_correlation,
        overall_verdict, evidence_summary
    """
    formula = _formula_similarity(factor1_spec, factor2_spec)
    exposure = _exposure_correlation(factor1_df, factor2_df)
    ret = _return_correlation(factor1_df, factor2_df)
    verdict, summary = _overall_verdict(formula, exposure, ret)

    return {
        "formula_similarity": formula,
        "exposure_correlation": exposure,
        "return_correlation": ret,
        "overall_verdict": verdict,
        "evidence_summary": summary,
    }


def detect_formula_similarity(spec1, spec2) -> dict | None:
    """公式相似度检测（公共接口，供 `09_鉴证运行.py` 使用）"""
    try:
        return _formula_similarity(spec1, spec2)
    except Exception:
        return None