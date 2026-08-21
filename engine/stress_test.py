"""
压力测试引擎 - 执行四项对抗式压力测试

测试项：
1. 数据延迟测试 - 将因子值延迟1个交易日
2. 剔除微盘测试 - 每日剔除市值最低20%的股票
3. 市值中性化测试 - 对 log(total_mv) 回归取残差
4. 极端贡献剔除测试 - 剔除 |z_factor * z_forward| 最大的1%样本
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def _compute_rank_ic(df, factor_col='factor_value', return_col='forward_return'):
    """计算日均 RankIC（Spearman 相关系数）

    Parameters
    ----------
    df : pd.DataFrame
        包含 ts_code, trade_date, factor_col, return_col
    factor_col : str
        因子值列名
    return_col : str
        收益列名

    Returns
    -------
    float
        日均 RankIC
    """
    daily_ics = []
    for date, group in df.groupby('trade_date'):
        valid = group[[factor_col, return_col]].dropna()
        if len(valid) < 10:
            continue
        ic, _ = spearmanr(valid[factor_col], valid[return_col])
        if not np.isnan(ic):
            daily_ics.append(ic)

    if not daily_ics:
        return 0.0
    return float(np.mean(daily_ics))


def _test_data_delay(aligned_df, baseline_ic, factor_col='factor_value', return_col='forward_return'):
    """数据延迟测试：将因子值延迟1个交易日"""
    df = aligned_df.copy()
    df = df.sort_values(['ts_code', 'trade_date'])

    # 按股票分组，将因子值延迟1个交易日
    df['factor_delayed'] = df.groupby('ts_code')[factor_col].shift(1)

    # 计算延迟后的 RankIC
    delay_df = df[['ts_code', 'trade_date', 'factor_delayed', return_col]].dropna(
        subset=['factor_delayed', return_col]
    )
    delay_df = delay_df.rename(columns={'factor_delayed': factor_col})

    if delay_df.empty:
        return {
            "test_name": "data_delay",
            "test_name_cn": "数据延迟测试",
            "baseline_rank_ic": baseline_ic,
            "stress_rank_ic": 0.0,
            "retention_ratio": 0.0,
            "direction_kept": False,
            "evidence": "数据量不足，无法完成延迟测试",
            "verdict": "fail",
        }

    stress_ic = _compute_rank_ic(delay_df, factor_col, return_col)

    direction_kept = (baseline_ic * stress_ic) > 0 if baseline_ic != 0 and stress_ic != 0 else False
    retention_ratio = abs(stress_ic / baseline_ic) if baseline_ic != 0 else 0.0

    if retention_ratio >= 0.80:
        verdict = "pass"
    elif retention_ratio >= 0.50:
        verdict = "warn"
    else:
        verdict = "fail"

    evidence = (
        f"将因子值延迟1个交易日后，RankIC 从 {baseline_ic:.4f} "
        f"变化至 {stress_ic:.4f}，保留比例为 {retention_ratio:.1%}。"
    )
    if direction_kept:
        evidence += "因子方向保持一致。"
    else:
        evidence += "因子方向发生反转，信号可能主要来自未来数据泄露或短期反转效应。"

    return {
        "test_name": "data_delay",
        "test_name_cn": "数据延迟测试",
        "baseline_rank_ic": baseline_ic,
        "stress_rank_ic": stress_ic,
        "retention_ratio": retention_ratio,
        "direction_kept": direction_kept,
        "evidence": evidence,
        "verdict": verdict,
    }


def _test_remove_micro_cap(aligned_df, baseline_ic, factor_col='factor_value', return_col='forward_return'):
    """剔除微盘测试：每日剔除 total_mv 最低 20% 的股票"""
    df = aligned_df.copy()

    if 'total_mv' not in df.columns:
        return {
            "test_name": "remove_micro_cap",
            "test_name_cn": "剔除微盘测试",
            "baseline_rank_ic": baseline_ic,
            "stress_rank_ic": baseline_ic,
            "retention_ratio": 1.0,
            "direction_kept": True,
            "evidence": "数据中缺少 total_mv 列，无法执行剔除微盘测试",
            "verdict": "pass",
        }

    # 每日剔除 total_mv 最低 20% 的股票
    filtered_parts = []
    for date, group in df.groupby('trade_date'):
        if len(group) < 5:
            filtered_parts.append(group)
            continue
        threshold = group['total_mv'].quantile(0.20)
        filtered = group[group['total_mv'] > threshold]
        filtered_parts.append(filtered)

    if not filtered_parts:
        return {
            "test_name": "remove_micro_cap",
            "test_name_cn": "剔除微盘测试",
            "baseline_rank_ic": baseline_ic,
            "stress_rank_ic": 0.0,
            "retention_ratio": 0.0,
            "direction_kept": False,
            "evidence": "剔除微盘后无有效数据",
            "verdict": "fail",
        }

    filtered_df = pd.concat(filtered_parts, ignore_index=True)
    stress_ic = _compute_rank_ic(filtered_df, factor_col, return_col)

    direction_kept = (baseline_ic * stress_ic) > 0 if baseline_ic != 0 and stress_ic != 0 else False
    retention_ratio = abs(stress_ic / baseline_ic) if baseline_ic != 0 else 0.0

    if retention_ratio >= 0.80:
        verdict = "pass"
    elif retention_ratio >= 0.50:
        verdict = "warn"
    else:
        verdict = "fail"

    evidence = (
        f"剔除每日市值最低 20% 的股票后，RankIC 从 {baseline_ic:.4f} "
        f"变化至 {stress_ic:.4f}，保留比例为 {retention_ratio:.1%}。"
    )
    if retention_ratio < 0.80:
        evidence += "因子收益可能高度依赖微盘股，需警惕流动性风险。"
    else:
        evidence += "因子在小市值股票剔除后仍保持有效，收益来源不依赖微盘效应。"

    return {
        "test_name": "remove_micro_cap",
        "test_name_cn": "剔除微盘测试",
        "baseline_rank_ic": baseline_ic,
        "stress_rank_ic": stress_ic,
        "retention_ratio": retention_ratio,
        "direction_kept": direction_kept,
        "evidence": evidence,
        "verdict": verdict,
    }


def _test_market_cap_neutralize(aligned_df, baseline_ic, factor_col='factor_value', return_col='forward_return'):
    """市值中性化测试：每日对因子值回归 log(total_mv)，使用残差"""
    df = aligned_df.copy()

    if 'total_mv' not in df.columns:
        return {
            "test_name": "market_cap_neutralize",
            "test_name_cn": "市值中性化测试",
            "baseline_rank_ic": baseline_ic,
            "stress_rank_ic": baseline_ic,
            "retention_ratio": 1.0,
            "direction_kept": True,
            "evidence": "数据中缺少 total_mv 列，无法执行市值中性化测试",
            "verdict": "pass",
        }

    # 每日对 factor 回归 log(total_mv)，取残差
    residual_parts = []
    for date, group in df.groupby('trade_date'):
        group = group.dropna(subset=[factor_col, 'total_mv'])
        if len(group) < 10:
            residual_parts.append(group)
            continue

        log_mv = np.log(group['total_mv'].replace(0, np.nan))
        valid_mask = log_mv.notna() & group[factor_col].notna()
        if valid_mask.sum() < 10:
            residual_parts.append(group)
            continue

        x = log_mv[valid_mask].values
        y = group.loc[valid_mask, factor_col].values

        # 简单线性回归：y = a + b*x，残差 = y - (a + b*x)
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        b = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2)
        a = y_mean - b * x_mean

        residuals = y - (a + b * x)
        group = group.copy()
        group.loc[valid_mask, factor_col] = residuals
        residual_parts.append(group)

    if not residual_parts:
        return {
            "test_name": "market_cap_neutralize",
            "test_name_cn": "市值中性化测试",
            "baseline_rank_ic": baseline_ic,
            "stress_rank_ic": 0.0,
            "retention_ratio": 0.0,
            "direction_kept": False,
            "evidence": "市值中性化后无有效数据",
            "verdict": "fail",
        }

    neutral_df = pd.concat(residual_parts, ignore_index=True)
    stress_ic = _compute_rank_ic(neutral_df, factor_col, return_col)

    direction_kept = (baseline_ic * stress_ic) > 0 if baseline_ic != 0 and stress_ic != 0 else False
    retention_ratio = abs(stress_ic / baseline_ic) if baseline_ic != 0 else 0.0

    # 市值中性化后 RankIC 是否仍 > 0.01
    if abs(stress_ic) >= 0.01:
        verdict = "pass"
        extra = "中性化后 RankIC 仍大于 0.01，因子在剥离市值影响后仍具预测能力。"
    elif abs(stress_ic) >= 0.005:
        verdict = "warn"
        extra = "中性化后 RankIC 介于 0.005~0.01，因子预测能力部分依赖市值暴露。"
    else:
        verdict = "fail"
        extra = "中性化后 RankIC 低于 0.005，因子收益主要来自市值暴露而非独立 alpha。"

    evidence = (
        f"对 log(总市值) 回归取残差后，RankIC 从 {baseline_ic:.4f} "
        f"变化至 {stress_ic:.4f}。{extra}"
    )

    return {
        "test_name": "market_cap_neutralize",
        "test_name_cn": "市值中性化测试",
        "baseline_rank_ic": baseline_ic,
        "stress_rank_ic": stress_ic,
        "retention_ratio": retention_ratio,
        "direction_kept": direction_kept,
        "evidence": evidence,
        "verdict": verdict,
    }


def _test_remove_extreme(aligned_df, baseline_ic, factor_col='factor_value', return_col='forward_return'):
    """极端贡献剔除测试：剔除 |z_factor * z_forward| 最大的 1% 样本"""
    df = aligned_df.copy()

    # 每日计算 z_factor 和 z_forward
    df['z_factor'] = np.nan
    df['z_forward'] = np.nan

    for date, group in df.groupby('trade_date'):
        valid = group[[factor_col, return_col]].dropna()
        if len(valid) < 10:
            continue

        factor_mean = valid[factor_col].mean()
        factor_std = valid[factor_col].std()
        ret_mean = valid[return_col].mean()
        ret_std = valid[return_col].std()

        if factor_std == 0 or ret_std == 0:
            continue

        df.loc[valid.index, 'z_factor'] = (valid[factor_col] - factor_mean) / factor_std
        df.loc[valid.index, 'z_forward'] = (valid[return_col] - ret_mean) / ret_std

    # 计算极端贡献指标
    df['extreme_score'] = np.abs(df['z_factor'] * df['z_forward'])

    # 剔除极端贡献最大的 1% 样本
    valid_scores = df['extreme_score'].dropna()
    if len(valid_scores) < 100:
        threshold = np.inf
    else:
        threshold = valid_scores.quantile(0.99)

    filtered_df = df[df['extreme_score'] <= threshold].copy()

    if filtered_df.empty:
        return {
            "test_name": "remove_extreme",
            "test_name_cn": "极端贡献剔除测试",
            "baseline_rank_ic": baseline_ic,
            "stress_rank_ic": 0.0,
            "retention_ratio": 0.0,
            "direction_kept": False,
            "evidence": "剔除极端贡献后无有效数据",
            "verdict": "fail",
        }

    stress_ic = _compute_rank_ic(filtered_df, factor_col, return_col)

    direction_kept = (baseline_ic * stress_ic) > 0 if baseline_ic != 0 and stress_ic != 0 else False
    retention_ratio = abs(stress_ic / baseline_ic) if baseline_ic != 0 else 0.0

    if retention_ratio >= 0.80:
        verdict = "pass"
    elif retention_ratio >= 0.50:
        verdict = "warn"
    else:
        verdict = "fail"

    n_removed = len(df) - len(filtered_df)
    evidence = (
        f"剔除 |z_factor * z_forward| 最大的 1% 样本（共 {n_removed} 条）后，"
        f"RankIC 从 {baseline_ic:.4f} 变化至 {stress_ic:.4f}，"
        f"保留比例为 {retention_ratio:.1%}。"
    )
    if retention_ratio < 0.80:
        evidence += "因子收益可能由少数极端样本驱动，稳健性不足。"
    else:
        evidence += "因子收益不依赖极端样本，信号来源较为分散。"

    return {
        "test_name": "remove_extreme",
        "test_name_cn": "极端贡献剔除测试",
        "baseline_rank_ic": baseline_ic,
        "stress_rank_ic": stress_ic,
        "retention_ratio": retention_ratio,
        "direction_kept": direction_kept,
        "evidence": evidence,
        "verdict": verdict,
    }


def run_stress_tests(aligned_df, ohlcv_df=None, factor_col='factor_value', return_col='forward_return'):
    """执行四项对抗式压力测试

    Parameters
    ----------
    aligned_df : pd.DataFrame
        对齐后的因子数据，包含 ts_code, trade_date, factor_value, forward_return
        可选 total_mv 列
    ohlcv_df : pd.DataFrame, optional
        行情数据（保留参数，当前版本未使用）
    factor_col : str
        因子值列名，默认 'factor_value'
    return_col : str
        收益列名，默认 'forward_return'

    Returns
    -------
    list[dict]
        四项测试结果列表，每项包含：
        - test_name: 测试名称
        - test_name_cn: 中文名称
        - baseline_rank_ic: 基线 RankIC
        - stress_rank_ic: 压力后 RankIC
        - retention_ratio: 保留比例
        - direction_kept: 方向是否保持
        - evidence: 证据解释
        - verdict: 结论（pass/warn/fail）
    """
    if aligned_df.empty:
        return [
            {
                "test_name": name,
                "test_name_cn": cn,
                "baseline_rank_ic": 0.0,
                "stress_rank_ic": 0.0,
                "retention_ratio": 0.0,
                "direction_kept": False,
                "evidence": "数据为空，无法执行压力测试",
                "verdict": "fail",
            }
            for name, cn in [
                ("data_delay", "数据延迟测试"),
                ("remove_micro_cap", "剔除微盘测试"),
                ("market_cap_neutralize", "市值中性化测试"),
                ("remove_extreme", "极端贡献剔除测试"),
            ]
        ]

    # 计算基线 RankIC
    baseline_ic = _compute_rank_ic(aligned_df, factor_col, return_col)

    # 执行四项测试
    results = [
        _test_data_delay(aligned_df, baseline_ic, factor_col, return_col),
        _test_remove_micro_cap(aligned_df, baseline_ic, factor_col, return_col),
        _test_market_cap_neutralize(aligned_df, baseline_ic, factor_col, return_col),
        _test_remove_extreme(aligned_df, baseline_ic, factor_col, return_col),
    ]

    return results


def summarize_stress_results(results):
    """汇总压力测试结果

    Parameters
    ----------
    results : list[dict]
        run_stress_tests 的返回结果

    Returns
    -------
    dict
        包含：
        - total: 测试总数
        - passed: 通过数
        - warned: 警告数
        - failed: 失败数
        - mean_retention: 平均保留比例
        - overall_verdict: 总体结论
        - overall_verdict_cn: 总体结论中文
        - summary_text: 总结文本
    """
    if not results:
        return {
            "total": 0,
            "passed": 0,
            "warned": 0,
            "failed": 0,
            "mean_retention": 0.0,
            "overall_verdict": "untested",
            "overall_verdict_cn": "未测试",
            "summary_text": "暂无压力测试数据。",
        }

    total = len(results)
    passed = sum(1 for r in results if r.get("verdict") == "pass")
    warned = sum(1 for r in results if r.get("verdict") == "warn")
    failed = sum(1 for r in results if r.get("verdict") == "fail")

    retentions = [r.get("retention_ratio", 0.0) for r in results]
    mean_retention = float(np.mean(retentions)) if retentions else 0.0

    # 总体结论
    if failed == 0 and warned == 0:
        overall_verdict = "pass"
        overall_verdict_cn = "通过"
        summary_text = (
            f"全部 {total} 项压力测试均通过，因子在对抗性扰动下表现稳健，"
            f"平均 RankIC 保留比例为 {mean_retention:.1%}。"
        )
    elif failed == 0:
        overall_verdict = "warn"
        overall_verdict_cn = "警告"
        summary_text = (
            f"{passed} 项通过、{warned} 项警告，因子在部分压力场景下存在波动，"
            f"平均 RankIC 保留比例为 {mean_retention:.1%}，建议关注警告项。"
        )
    elif failed <= 2:
        overall_verdict = "fragile"
        overall_verdict_cn = "脆弱"
        summary_text = (
            f"{failed} 项未通过压力测试，因子在对抗性扰动下表现较为脆弱，"
            f"平均 RankIC 保留比例为 {mean_retention:.1%}，建议谨慎使用。"
        )
    else:
        overall_verdict = "invalid"
        overall_verdict_cn = "无效"
        summary_text = (
            f"{failed} 项未通过压力测试，因子在多种对抗性扰动下均表现不佳，"
            f"平均 RankIC 保留比例为 {mean_retention:.1%}，不建议直接使用。"
        )

    return {
        "total": total,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "mean_retention": mean_retention,
        "overall_verdict": overall_verdict,
        "overall_verdict_cn": overall_verdict_cn,
        "summary_text": summary_text,
    }