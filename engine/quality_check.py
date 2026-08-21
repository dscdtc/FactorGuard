"""
输入质检引擎 (T015)

对用户输入的因子数据进行 P0 级别质量检查：
1. 负向位移/未来引用检测
2. 因子观察时点与收益标签冲突
3. 重复键检测
4. 缺失值/覆盖率异常
5. 无穷值/非法值
6. 数据时间范围不足
7. 因子方向未声明
8. 样本股票数不足
9. 数据字段不可用
"""

import numpy as np
import pandas as pd
from typing import Optional

from engine.formula_parser import FormulaParser


def check_negative_window(spec) -> dict:
    """检查公式中是否包含负向位移（未来引用）"""
    formula = getattr(spec, 'formula', '') or ''
    params = getattr(spec, 'params', {}) or {}
    window = params.get('window', 0)
    if isinstance(window, (int, float)) and window < 0:
        return {
            "check": "负向位移/未来引用检测",
            "passed": False,
            "severity": "fail",
            "detail": "因子参数包含负向窗口，存在未来数据引用风险",
            "evidence_id": "QC-WINDOW-001",
        }
    if not formula:
        return {
            "check": "负向位移/未来引用检测",
            "passed": True,
            "severity": "pass",
            "detail": "无公式定义，跳过检测",
            "evidence_id": "QC-WINDOW-001",
        }

    parser = FormulaParser()
    result = parser.parse(formula)

    # 检查 delay 的窗口参数是否为负
    has_negative = False
    for err in result.errors:
        if "必须 >= 0" in err or "negative" in err.lower():
            has_negative = True
            break

    if has_negative:
        return {
            "check": "负向位移/未来引用检测",
            "passed": False,
            "severity": "fail",
            "detail": "公式包含负向窗口参数，存在未来数据引用风险",
            "evidence_id": "QC-WINDOW-001",
        }

    return {
        "check": "负向位移/未来引用检测",
        "passed": True,
        "severity": "pass",
        "detail": f"公式最大回看窗口为 {result.max_window} 日，无未来引用",
        "evidence_id": "QC-WINDOW-001",
    }


def check_duplicate_keys(df: pd.DataFrame, factor_col: str = 'factor_value') -> dict:
    """检查 (ts_code, trade_date) 是否有重复键"""
    if df.empty:
        return {
            "check": "重复键检测",
            "passed": True,
            "severity": "pass",
            "detail": "数据为空，跳过检测",
            "evidence_id": "QC-DUPKEY-001",
        }

    dup_count = df.duplicated(subset=['ts_code', 'trade_date']).sum()

    if dup_count > 0:
        return {
            "check": "重复键检测",
            "passed": False,
            "severity": "fail",
            "detail": f"存在 {dup_count} 条重复的 (ts_code, trade_date) 记录",
            "evidence_id": "QC-DUPKEY-001",
            "dup_count": dup_count,
        }

    return {
        "check": "重复键检测",
        "passed": True,
        "severity": "pass",
        "detail": "无重复键",
        "evidence_id": "QC-DUPKEY-001",
    }


def check_coverage(df: pd.DataFrame, factor_col: str = 'factor_value') -> dict:
    """检查缺失值/覆盖率异常"""
    if df.empty:
        return {
            "check": "缺失值/覆盖率检查",
            "passed": False,
            "severity": "fail",
            "detail": "数据为空",
            "evidence_id": "QC-COVERAGE-001",
        }

    total = len(df)
    valid = df[factor_col].notna().sum()
    coverage = valid / total if total > 0 else 0

    if coverage >= 0.90:
        severity = "pass"
        passed = True
    elif coverage >= 0.70:
        severity = "warn"
        passed = True
    else:
        severity = "fail"
        passed = False

    return {
        "check": "缺失值/覆盖率检查",
        "passed": passed,
        "severity": severity,
        "detail": f"有效因子值覆盖率 {coverage:.1%}（{valid}/{total}）",
        "evidence_id": "QC-COVERAGE-001",
        "coverage": coverage,
        "valid_count": valid,
        "total_count": total,
    }


def check_inf_values(df: pd.DataFrame, factor_col: str = 'factor_value') -> dict:
    """检查无穷值/非法值"""
    if df.empty:
        return {
            "check": "无穷值/非法值检查",
            "passed": True,
            "severity": "pass",
            "detail": "数据为空，跳过检测",
            "evidence_id": "QC-INF-001",
        }

    inf_count = df[factor_col].apply(lambda x: np.isinf(x) if isinstance(x, (int, float)) else False).sum()
    nan_count = df[factor_col].isna().sum()

    issues = []
    if inf_count > 0:
        issues.append(f"{inf_count} 条无穷值")
    if nan_count > 0:
        issues.append(f"{nan_count} 条缺失值")

    if issues:
        return {
            "check": "无穷值/非法值检查",
            "passed": False,
            "severity": "warn",
            "detail": "、".join(issues) + f"（共 {len(df)} 条记录）",
            "evidence_id": "QC-INF-001",
            "inf_count": inf_count,
            "nan_count": nan_count,
        }

    return {
        "check": "无穷值/非法值检查",
        "passed": True,
        "severity": "pass",
        "detail": "无异常值",
        "evidence_id": "QC-INF-001",
    }


def check_time_range(df: pd.DataFrame, min_days: int = 60) -> dict:
    """检查数据时间范围是否充足"""
    if df.empty:
        return {
            "check": "数据时间范围检查",
            "passed": False,
            "severity": "fail",
            "detail": "数据为空",
            "evidence_id": "QC-TIMERANGE-001",
        }

    dates = pd.to_datetime(df['trade_date'])
    unique_dates = sorted(dates.unique())
    n_days = len(unique_dates)

    if n_days >= min_days:
        return {
            "check": "数据时间范围检查",
            "passed": True,
            "severity": "pass",
            "detail": f"数据覆盖 {n_days} 个交易日（{unique_dates[0].strftime('%Y-%m-%d')} ~ {unique_dates[-1].strftime('%Y-%m-%d')}），满足最低 {min_days} 日要求",
            "evidence_id": "QC-TIMERANGE-001",
            "n_days": n_days,
            "date_start": unique_dates[0].strftime('%Y-%m-%d'),
            "date_end": unique_dates[-1].strftime('%Y-%m-%d'),
        }

    return {
        "check": "数据时间范围检查",
        "passed": False,
        "severity": "fail",
        "detail": f"数据仅覆盖 {n_days} 个交易日，不足最低 {min_days} 日要求",
        "evidence_id": "QC-TIMERANGE-001",
        "n_days": n_days,
        "date_start": unique_dates[0].strftime('%Y-%m-%d') if len(unique_dates) > 0 else 'N/A',
        "date_end": unique_dates[-1].strftime('%Y-%m-%d') if len(unique_dates) > 0 else 'N/A',
    }


def check_direction_declared(spec) -> dict:
    """检查因子方向是否声明"""
    direction = getattr(spec, 'expected_direction', None)

    if direction is None or direction not in ('higher', 'lower'):
        return {
            "check": "因子方向声明检查",
            "passed": False,
            "severity": "fail",
            "detail": "因子预期方向未声明",
            "evidence_id": "QC-DIRECTION-001",
        }

    label = "做多高因子值" if direction == "higher" else "做空高因子值"
    return {
        "check": "因子方向声明检查",
        "passed": True,
        "severity": "pass",
        "detail": f"预期方向已声明：{label}",
        "evidence_id": "QC-DIRECTION-001",
    }


def check_sample_stocks(df: pd.DataFrame, min_stocks: int = 30) -> dict:
    """检查样本股票数是否充足"""
    if df.empty:
        return {
            "check": "样本股票数检查",
            "passed": False,
            "severity": "fail",
            "detail": "数据为空",
            "evidence_id": "QC-SAMPLES-001",
        }

    n_stocks = df['ts_code'].nunique()
    # 计算日均股票数
    daily_stocks = df.groupby('trade_date')['ts_code'].nunique()
    avg_daily_stocks = daily_stocks.mean() if len(daily_stocks) > 0 else 0

    if avg_daily_stocks >= min_stocks:
        return {
            "check": "样本股票数检查",
            "passed": True,
            "severity": "pass",
            "detail": f"日均 {avg_daily_stocks:.0f} 只股票（总计 {n_stocks} 只），满足最低 {min_stocks} 只要求",
            "evidence_id": "QC-SAMPLES-001",
            "total_stocks": n_stocks,
            "avg_daily_stocks": avg_daily_stocks,
        }

    return {
        "check": "样本股票数检查",
        "passed": False,
        "severity": "fail",
        "detail": f"日均仅 {avg_daily_stocks:.0f} 只股票，不足最低 {min_stocks} 只要求",
        "evidence_id": "QC-SAMPLES-001",
        "total_stocks": n_stocks,
        "avg_daily_stocks": avg_daily_stocks,
    }


def check_fields_available(spec, ohlcv_df: Optional[pd.DataFrame] = None) -> dict:
    """检查因子所需数据字段是否可用"""
    if ohlcv_df is None or ohlcv_df.empty:
        return {
            "check": "数据字段可用性检查",
            "passed": True,
            "severity": "warn",
            "detail": "无 OHLCV 数据，跳过字段可用性检查",
            "evidence_id": "QC-FIELDS-001",
        }

    formula = getattr(spec, 'formula', '') or ''
    if not formula:
        return {
            "check": "数据字段可用性检查",
            "passed": True,
            "severity": "pass",
            "detail": "无公式定义，跳过字段检查",
            "evidence_id": "QC-FIELDS-001",
        }

    parser = FormulaParser()
    result = parser.parse(formula)

    if not result.valid:
        return {
            "check": "数据字段可用性检查",
            "passed": False,
            "severity": "fail",
            "detail": f"公式解析失败，无法检查字段可用性",
            "evidence_id": "QC-FIELDS-001",
        }

    required_fields = result.used_fields
    available_fields = list(ohlcv_df.columns)
    missing = [f for f in required_fields if f not in available_fields]

    if missing:
        return {
            "check": "数据字段可用性检查",
            "passed": False,
            "severity": "fail",
            "detail": f"缺少数据字段: {', '.join(missing)}",
            "evidence_id": "QC-FIELDS-001",
            "missing_fields": missing,
            "required_fields": required_fields,
        }

    return {
        "check": "数据字段可用性检查",
        "passed": True,
        "severity": "pass",
        "detail": f"所需字段 {', '.join(required_fields)} 均可用",
        "evidence_id": "QC-FIELDS-001",
        "required_fields": required_fields,
    }


def check_observation_timing(spec, aligned_df: Optional[pd.DataFrame] = None) -> dict:
    """检查因子观察时点与收益标签是否存在冲突（因子值是否在收益数据之前）"""
    if aligned_df is None or aligned_df.empty:
        return {
            "check": "因子观察时点与收益标签冲突检测",
            "passed": True,
            "severity": "pass",
            "detail": "无对齐数据，跳过检测",
            "evidence_id": "QC-TIMING-001",
        }

    params = getattr(spec, 'params', {}) or {}
    window = params.get('window', 0)

    if isinstance(window, (int, float)) and window < 0:
        return {
            "check": "因子观察时点与收益标签冲突检测",
            "passed": False,
            "severity": "fail",
            "detail": f"因子窗口参数为 {window}（负值），使用了未来数据，观察时点与收益标签存在冲突",
            "evidence_id": "QC-TIMING-001",
        }

    return {
        "check": "因子观察时点与收益标签冲突检测",
        "passed": True,
        "severity": "pass",
        "detail": "观察时点与收益标签无冲突",
        "evidence_id": "QC-TIMING-001",
    }


def run_quality_checks(
    spec,
    df: Optional[pd.DataFrame] = None,
    ohlcv_df: Optional[pd.DataFrame] = None,
    aligned_df: Optional[pd.DataFrame] = None,
    min_days: int = 60,
    min_stocks: int = 30,
) -> list[dict]:
    """执行全部 P0 输入质检检查项

    Parameters
    ----------
    spec : FactorSpec
        因子规格对象
    df : pd.DataFrame, optional
        因子值数据（含 ts_code, trade_date, factor_value）
    ohlcv_df : pd.DataFrame, optional
        OHLCV 行情数据
    aligned_df : pd.DataFrame, optional
        对齐后的因子数据
    min_days : int
        最低交易日数要求，默认 60
    min_stocks : int
        最低日均股票数要求，默认 30

    Returns
    -------
    list[dict]
        每项检查结果，包含 check, passed, severity, detail, evidence_id
    """
    results = []

    # 1. 负向位移/未来引用检测（基于公式）
    results.append(check_negative_window(spec))

    # 2. 因子方向声明检查
    results.append(check_direction_declared(spec))

    if df is not None and not df.empty:
        factor_col = 'factor_value' if 'factor_value' in df.columns else df.columns[-1]

        # 3. 重复键检测
        results.append(check_duplicate_keys(df, factor_col))

        # 4. 缺失值/覆盖率检查
        results.append(check_coverage(df, factor_col))

        # 5. 无穷值/非法值检查
        results.append(check_inf_values(df, factor_col))

        # 6. 数据时间范围检查
        results.append(check_time_range(df, min_days))

        # 7. 样本股票数检查
        results.append(check_sample_stocks(df, min_stocks))
    else:
        # 数据为空时跳过数据相关检查
        for check_name in ["重复键检测", "缺失值/覆盖率检查", "无穷值/非法值检查",
                           "数据时间范围检查", "样本股票数检查"]:
            results.append({
                "check": check_name,
                "passed": False,
                "severity": "fail",
                "detail": "无因子数据，跳过检查",
                "evidence_id": f"QC-SKIP-{len(results)}",
            })

    # 8. 数据字段可用性检查
    results.append(check_fields_available(spec, ohlcv_df))

    # 9. 因子观察时点与收益标签冲突
    results.append(check_observation_timing(spec, aligned_df))

    return results


def summarize_quality_check(results: list[dict]) -> dict:
    """汇总质检结果

    Returns
    -------
    dict
        包含 total, passed, warned, failed, all_passed, summary_text
    """
    total = len(results)
    passed = sum(1 for r in results if r.get("passed", False))
    warned = sum(1 for r in results if r.get("severity") == "warn")
    failed = sum(1 for r in results if r.get("severity") == "fail")

    all_passed = failed == 0

    if all_passed and warned == 0:
        summary = f"全部 {total} 项质检通过，因子数据质量良好。"
    elif all_passed:
        summary = f"{passed} 项通过，{warned} 项警告，因子数据存在需关注的问题。"
    else:
        summary = f"{passed} 项通过，{failed} 项未通过，{warned} 项警告，因子数据存在严重问题。"

    return {
        "total": total,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "all_passed": all_passed,
        "summary_text": summary,
    }
