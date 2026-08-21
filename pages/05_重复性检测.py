"""
因子重复性检测页面
"""
import json
import streamlit as st
import pandas as pd
from pathlib import Path

from config import FACTORS_DIR
from engine.duplicate_detect import detect_duplicates
from engine.data_aligner import align_factor_returns
from engine.data_loader import get_ohlcv_data, get_basic_data
from engine.factor_loader import get_all_factors, get_factor_by_id
from engine.factor_computer import compute_factor_values
from engine.run_recorder import save_run
from engine.session_context import build_cache_context, contextual_cache_key, set_audit_result
from ui.metric_cards import render_verdict_badge
from ui.chart_utils import create_radar_chart

SKILL_REPOS = [
    "skill-quant-factor-directional-alpha",
    "skill-quant-factor-risk-pattern-alpha",
    "skill-quant-factor-volume-stat-alpha",
]


def _render_result(result, spec1_name: str, spec2_name: str):
    """统一渲染重复检测结果。"""
    st.markdown("---")
    st.subheader("检测结果")

    verdict_map = {
        "高度相似": "supported",
        "中等相似": "conditional",
        "不相似": "invalid",
    }
    badge_verdict = verdict_map.get(result["overall_verdict"], "insufficient")

    vcol1, vcol2, vcol3 = st.columns([1, 1, 2])
    with vcol1:
        render_verdict_badge(badge_verdict)
    with vcol2:
        st.markdown(
            f"<h2 style='margin-top:0;'>{result['overall_verdict']}</h2>",
            unsafe_allow_html=True
        )
    with vcol3:
        st.info(result["evidence_summary"])

    st.markdown("---")
    st.subheader("📊 三层证据")

    radar_values = [
        result["formula_similarity"]["score"],
        result["exposure_correlation"]["score"],
        result["return_correlation"]["score"],
    ]
    radar_labels = ["公式结构", "暴露相关", "收益相关"]
    radar_fig = create_radar_chart(radar_labels, radar_values, title="证据雷达")
    st.plotly_chart(radar_fig, width="stretch")

    ev1, ev2, ev3 = st.columns(3)
    level_icon = {"high": "🟢", "medium": "🟠", "low": "🔴"}

    with ev1:
        st.markdown("#### 📐 公式结构相似度")
        fs = result["formula_similarity"]
        st.progress(fs["score"], text=f"{fs['score']:.2%}")
        st.caption(f"{level_icon.get(fs['level'], '⚪')} {fs['details']}")

    with ev2:
        st.markdown("#### 📈 横截面暴露相关性")
        ec = result["exposure_correlation"]
        st.progress(ec["score"], text=f"{ec['score']:.2%}")
        st.caption(f"{level_icon.get(ec['level'], '⚪')} {ec['details']}")

    with ev3:
        st.markdown("#### 💰 因子收益相关性")
        rc = result["return_correlation"]
        st.progress(rc["score"], text=f"{rc['score']:.2%}")
        st.caption(f"{level_icon.get(rc['level'], '⚪')} {rc['details']}")

    st.markdown("---")
    st.caption(
        "判定规则：暴露相关 > 0.85 且 收益相关 > 0.80 → 高度相似；"
        "暴露相关 > 0.70 且 收益相关 > 0.65 → 中等相似；其他 → 不相似。"
    )


def _load_factor_values(factor_id):
    """加载因子的对齐数据（含 factor_value 和 forward_return）"""
    spec = get_factor_by_id(factor_id)
    if spec is None:
        st.error(f"未找到因子 {factor_id} 的定义")
        return pd.DataFrame()

    with st.spinner(f"正在加载 {spec.name_cn} 数据..."):
        ohlcv = get_ohlcv_data()
        if ohlcv is None or ohlcv.empty:
            st.error("OHLCV 数据加载失败")
            return pd.DataFrame()

        factor_vals = compute_factor_values(ohlcv, spec)
        if factor_vals is None or factor_vals.empty:
            st.error(f"因子值计算失败（{spec.name_cn}）")
            return pd.DataFrame()

        basic = get_basic_data()
        if basic is None or basic.empty:
            st.error("基本面数据加载失败")
            return pd.DataFrame()

        aligned = align_factor_returns(factor_vals, ohlcv, basic)
        if aligned is None or aligned.empty:
            st.error(f"数据对齐失败（{spec.name_cn}）")
            return pd.DataFrame()

    return aligned


st.set_page_config(page_title="因子重复性检测", page_icon="🔁", layout="wide")
st.title("🔁 因子重复性检测")

st.caption("对比两个因子，检测它们在结构、暴露和收益上的重合程度。")

# Demo B 特殊处理：自动选择重复因子对
is_demo_b = st.session_state.get("is_demo", False) and st.session_state.get("selected_factor_id") == "demo_duplicate"

# 获取因子列表
with st.spinner("加载因子列表..."):
    all_specs = get_all_factors()
    factor_options = {s.factor_id: f"{s.factor_id} - {s.name_cn}" for s in all_specs}

if not factor_options:
    st.warning("未找到因子数据，请先确保因子库已初始化。")
    st.stop()

# ---- 因子选择 ----
col1, col2 = st.columns(2)
with col1:
    # Demo B 默认选择 R001
    f1_default = "R001" if is_demo_b and "R001" in factor_options else 0
    if is_demo_b and "R001" in factor_options:
        f1_idx = list(factor_options.keys()).index("R001")
    else:
        f1_idx = 0
    factor1_id = st.selectbox(
        "因子 A",
        options=list(factor_options.keys()),
        index=f1_idx,
        format_func=lambda x: factor_options[x],
        key="factor1"
    )
with col2:
    # Demo B 默认选择 R034
    if is_demo_b and "R034" in factor_options:
        f2_idx = list(factor_options.keys()).index("R034")
    else:
        f2_default_idx = 1 if len(factor_options) > 1 else 0
        f2_idx = min(f2_default_idx, len(factor_options) - 1)
    factor2_id = st.selectbox(
        "因子 B",
        options=list(factor_options.keys()),
        index=f2_idx,
        format_func=lambda x: factor_options[x],
        key="factor2"
    )

# Demo B 提示
if is_demo_b:
    st.info("🧪 **Demo B: 重复因子检测** — 已自动选择 R001 和 R034，它们是两个公式结构相似但命名不同的因子。点击下方按钮开始检测。")
    # 清除 demo 标记，避免影响后续操作
    st.session_state["is_demo"] = False

if factor1_id == factor2_id:
    st.warning("请选择两个不同的因子进行比较。")
    st.stop()

existing_dup = st.session_state.get("audit_results", {}).get("duplicate_check")
if isinstance(existing_dup, dict) and existing_dup.get("status") == "passed":
    duplicates_found = existing_dup.get("duplicates_found", 0)
    overall_verdict = "不相似" if duplicates_found == 0 else ("中等相似" if duplicates_found == 1 else "高度相似")
    result = {
        "overall_verdict": overall_verdict,
        "evidence_summary": f"当前结果来自鉴证流程缓存：发现 {duplicates_found} 个疑似重复因子。",
        "formula_similarity": {
            "score": 0.2 if duplicates_found == 0 else 0.75,
            "level": "low" if duplicates_found == 0 else "medium",
            "details": "演示模式下使用缓存结果生成摘要。",
        },
        "exposure_correlation": {
            "score": 0.15 if duplicates_found == 0 else 0.72,
            "level": "low" if duplicates_found == 0 else "medium",
            "details": "演示模式下使用缓存结果生成摘要。",
        },
        "return_correlation": {
            "score": 0.12 if duplicates_found == 0 else 0.68,
            "level": "low" if duplicates_found == 0 else "medium",
            "details": "演示模式下使用缓存结果生成摘要。",
        },
    }
    st.info("📦 使用鉴证流程中的重复检测结果")
    _render_result(result, factor1_id, factor2_id)
    st.stop()

# ---- 执行检测 ----
if st.button("🔍 开始检测", type="primary", width="stretch"):
    cache_context = build_cache_context(
        st.session_state,
        compared_factor_ids=sorted([factor1_id, factor2_id]),
        forward_period=int(st.session_state.get("forward_period", 5)),
    )
    cache_key = contextual_cache_key("duplicate", cache_context)
    cached = st.session_state.get(cache_key)

    if cached is not None:
        st.info("📦 使用缓存数据（无需重新计算）")
        result = cached
    else:
        with st.spinner("正在加载数据并执行重复检测..."):
            factor1_aligned = _load_factor_values(factor1_id)
            factor2_aligned = _load_factor_values(factor2_id)

            if factor1_aligned.empty or factor2_aligned.empty:
                st.error("无法加载因子数据，请检查因子数据是否可用。")
                st.stop()

            spec1 = get_factor_by_id(factor1_id)
            spec2 = get_factor_by_id(factor2_id)

            if spec1 is None or spec2 is None:
                st.error("无法获取因子元数据。")
                st.stop()

        result = detect_duplicates(
                factor1_aligned, factor2_aligned, spec1, spec2
            )

        result["source"] = "computed"

        # 缓存计算结果
        st.session_state[cache_key] = result

        # 保存运行记录到工作台
        dup_verdict_map = {"高度相似": "fragile", "中等相似": "conditional", "不相似": "supported"}
        dup_verdict = dup_verdict_map.get(result.get("overall_verdict", ""), "insufficient")
        run_factor_id = st.session_state.get("selected_factor_id") or factor1_id
        save_run(f"{spec1.name_cn} vs {spec2.name_cn}", run_factor_id,
                 dup_verdict, result.get("evidence_summary", ""), st.session_state)

    result.setdefault("source", "computed")
    duplicate_bundle = dict(result)
    duplicate_bundle["compared_factor_ids"] = [factor1_id, factor2_id]
    duplicate_bundle["duplicates_found"] = 0 if result.get("overall_verdict") == "不相似" else 1
    set_audit_result(st.session_state, "duplicate_check", duplicate_bundle)

    _render_result(result, factor1_id, factor2_id)
