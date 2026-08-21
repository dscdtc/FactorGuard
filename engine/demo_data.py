"""
Demo 数据构造模块

为 FactorGuard 各校验场景提供预构造的 Demo 数据：
- Demo A: 未来函数（负 delay 触发时间正确性失败）
- Demo B: 重复因子对（公式结构相似的因子对）
- Demo C: 小微盘暴露（压力测试中剔除微盘后 RankIC 显著下降）
- Demo D: 大师方法（巴菲特质量框架及其代理因子）
"""

from engine.factor_loader import get_all_factors, get_factor_by_id, get_precomputed_metrics, load_all_factors
from engine.master_method_loader import load_demo_master_method
from models.factor_spec import FactorSpec
from config import FACTORS_DIR


# ---------------------------------------------------------------------------
# 内部辅助：确保因子库已加载到 DB，否则从因子目录加载
# ---------------------------------------------------------------------------

def _ensure_factors_loaded() -> list[FactorSpec]:
    """确保因子数据库已初始化，返回所有因子列表。"""
    factors = get_all_factors()
    if not factors:
        load_all_factors(FACTORS_DIR)
        factors = get_all_factors()
    return factors


# ---------------------------------------------------------------------------
# Demo A: 未来函数因子
# ---------------------------------------------------------------------------

def get_demo_a_factor() -> dict:
    """返回 Demo A 未来函数因子的模拟数据。

    选择一个 status="pass" 的内置因子，在 formula 中设置负 delay
    （如 delay=-1），触发时间正确性失败。

    Returns
    -------
    dict
        包含 factor_spec（已篡改 formula）和 precomputed_metrics 的字典
    """
    _ensure_factors_loaded()

    # 选择一个已知的 pass 因子：R001 (5日标准化收益动量)
    original_spec = get_factor_by_id("R001")
    if original_spec is None:
        return {
            "factor_spec": None,
            "precomputed_metrics": {},
            "error": "无法加载 R001 因子数据",
            "original_formula": None,
            "modified_formula": None,
        }

    original_formula = original_spec.formula or ""

    # 构造一个包含负 delay 的 formula，模拟未来函数
    modified_formula = "delay(close, -1) * z(return, window=5)"

    # 基于原始 spec 创建修改后的 spec（浅拷贝 dict 再重建）
    modified_spec = FactorSpec(
        factor_id=original_spec.factor_id,
        name=original_spec.name,
        name_cn=original_spec.name_cn,
        version=original_spec.version,
        description=original_spec.description,
        formula=modified_formula,
        formula_cn=original_spec.formula_cn,
        expected_direction=original_spec.expected_direction,
        category=original_spec.category,
        base=original_spec.base,
        transform=original_spec.transform,
        params=original_spec.params,
        inputs=original_spec.inputs,
        frequency=original_spec.frequency,
        availability=original_spec.availability,
        availability_lag=original_spec.availability_lag,
        min_window=original_spec.min_window,
        universe_rule=original_spec.universe_rule,
        preprocess=original_spec.preprocess,
        neutralization=original_spec.neutralization,
        source=original_spec.source,
        source_reference=original_spec.source_reference,
        rationale_cn=original_spec.rationale_cn,
    )

    metrics = get_precomputed_metrics(original_spec.factor_id)

    return {
        "factor_spec": modified_spec,
        "precomputed_metrics": metrics,
        "original_formula": original_formula,
        "modified_formula": modified_formula,
        "demo_note": "Demo A: 未来函数因子 — formula 中嵌入了 delay(close, -1)，"
                      "该负 delay 会调用未来数据，触发时间正确性校验失败。",
    }


# ---------------------------------------------------------------------------
# Demo B: 重复因子对
# ---------------------------------------------------------------------------

def get_demo_b_factors() -> dict:
    """返回 Demo B 重复因子对的模拟数据。

    选择两个公式结构相似但命名不同的因子（同属动量类别，
    一个使用 z-score 变换，一个使用 delta 变换）。

    Returns
    -------
    dict
        包含 factor_a, factor_b, metrics_a, metrics_b 的字典
    """
    _ensure_factors_loaded()

    # 选择两个动量因子：R001 (z-scored) 和 R034 (delta)
    factor_a = get_factor_by_id("R001")
    factor_b = get_factor_by_id("R034")

    if factor_a is None or factor_b is None:
        return {
            "factor_a": None,
            "factor_b": None,
            "metrics_a": {},
            "metrics_b": {},
            "error": "无法加载 R001 或 R034 因子数据",
        }

    metrics_a = get_precomputed_metrics(factor_a.factor_id)
    metrics_b = get_precomputed_metrics(factor_b.factor_id)

    return {
        "factor_a": factor_a,
        "factor_b": factor_b,
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "demo_note": "Demo B: 重复因子对 — R001 (z-scored return momentum) 与 "
                      "R034 (delta return momentum)，两者 base 均为 return、"
                      "window 均为 5，公式结构高度相似但命名不同。",
    }


# ---------------------------------------------------------------------------
# Demo C: 小微盘暴露因子
# ---------------------------------------------------------------------------

def get_demo_c_factor() -> dict:
    """返回 Demo C 小微盘暴露因子的模拟数据。

    选择一个 ic_mean_5d 较高的因子，在压力测试中模拟剔除微盘后
    RankIC 显著下降。

    Returns
    -------
    dict
        包含 factor_spec, precomputed_metrics, simulated_stress 的字典
    """
    _ensure_factors_loaded()

    # 选择 R072 (5日平滑双EMA趋势差)，ic_mean_5d ≈ 0.0102，status=pass
    spec = get_factor_by_id("R072")
    if spec is None:
        return {
            "factor_spec": None,
            "precomputed_metrics": {},
            "simulated_stress": {},
            "error": "无法加载 R072 因子数据",
        }

    metrics = get_precomputed_metrics(spec.factor_id)
    baseline_ic = metrics.get("ic_mean_5d", 0.0102)

    # 模拟剔除微盘后的压力测试结果：RankIC 显著下降
    simulated_stress = {
        "test_name": "micro_cap_exclusion",
        "test_name_cn": "剔除微盘测试",
        "description": "每日剔除市值最低 20% 的股票后重新计算因子 RankIC",
        "baseline_rank_ic": round(baseline_ic, 6),
        "stress_rank_ic": round(baseline_ic * 0.25, 6),  # 模拟 RankIC 下降到原来的 25%
        "retention_ratio": 0.25,
        "direction_kept": baseline_ic > 0 and (baseline_ic * 0.25) > 0,
        "evidence": (
            "剔除微盘后 RankIC 从 {:.6f} 下降到 {:.6f}，"
            "保留率仅 25%，表明因子收益高度依赖微盘股贡献。"
            "该因子在小微盘暴露方面存在严重风险。"
        ).format(baseline_ic, baseline_ic * 0.25),
        "verdict": "fail",
        "is_simulated": True,
    }

    return {
        "factor_spec": spec,
        "precomputed_metrics": metrics,
        "simulated_stress": simulated_stress,
        "demo_note": "Demo C: 小微盘暴露因子 — R072 原始 ic_mean_5d 较高，"
                      "但剔除微盘后 RankIC 保留率仅 25%，暴露严重小微盘依赖。",
    }


# ---------------------------------------------------------------------------
# Demo D: 大师方法
# ---------------------------------------------------------------------------

def get_demo_d_data() -> dict:
    """返回 Demo D 大师方法数据。

    调用 engine.master_method_loader.load_demo_master_method()，
    返回大师方法规格和代理因子数据。

    Returns
    -------
    dict
        包含 master_method, proxy_factors_data 的字典
    """
    try:
        master_method = load_demo_master_method()
    except Exception as e:
        return {
            "master_method": None,
            "proxy_factors_data": {},
            "error": f"加载大师方法失败: {e}",
        }

    _ensure_factors_loaded()

    # 为每个原则中的代理因子尝试匹配内置因子
    proxy_factors_data = {}
    for principle in master_method.principles:
        for proxy_name in principle.proxy_factors:
            all_factors = get_all_factors()
            matched = None
            for f in all_factors:
                if proxy_name in f.name_cn or proxy_name in f.name:
                    matched = f
                    break
            proxy_factors_data[proxy_name] = {
                "matched_factor": matched,
                "metrics": get_precomputed_metrics(matched.factor_id) if matched else {},
            }

    return {
        "master_method": master_method,
        "proxy_factors_data": proxy_factors_data,
        "demo_note": "Demo D: 大师方法 — 巴菲特质量框架（去劣筛选），"
                      "包含 7 条原则和 3 条豁免规则。",
    }


# ---------------------------------------------------------------------------
# 初始化 Demo 数据到 session_state
# ---------------------------------------------------------------------------

def init_demo_session_state():
    """在 session_state 中初始化 Demo 数据。

    将 demo_a、demo_b、demo_c、demo_d 写入 st.session_state。
    """
    import streamlit as st

    if "demo_a" not in st.session_state:
        st.session_state.demo_a = get_demo_a_factor()
    if "demo_b" not in st.session_state:
        st.session_state.demo_b = get_demo_b_factors()
    if "demo_c" not in st.session_state:
        st.session_state.demo_c = get_demo_c_factor()
    if "demo_d" not in st.session_state:
        st.session_state.demo_d = get_demo_d_data()