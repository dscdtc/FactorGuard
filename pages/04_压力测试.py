"""
压力测试页面 - 因子对抗式压力测试结果展示
"""

import streamlit as st
import pandas as pd

from engine.stress_test import run_stress_tests, summarize_stress_results
from engine.factor_computer import load_aligned_data
from engine.run_recorder import save_run
from engine.session_context import build_cache_context, contextual_cache_key, set_audit_result
from ui.metric_cards import render_verdict_badge
from ui.color_utils import get_verdict_color
from config import COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL, COLOR_UNTESTED

st.set_page_config(page_title="压力测试", page_icon="💪", layout="wide")


def _build_fallback_stress_from_eval(eval_results: dict) -> tuple[list[dict], dict]:
    """在无实时数据时，用已有评估结果构造轻量压力测试摘要。"""
    base_rank_ic = eval_results.get("rank_ic_mean", 0.0)
    test_results = [
        {
            "test_name": "precomputed_proxy",
            "test_name_cn": "预计算稳健性代理",
            "baseline_rank_ic": base_rank_ic,
            "stress_rank_ic": None,
            "retention_ratio": None,
            "direction_kept": None,
            "verdict": "untested",
            "source": "demo",
            "evidence": "基于预计算 ICIR 和覆盖率构造的演示级稳健性摘要，供无本地数据时路演使用。",
        }
    ]
    summary = {
        "overall_verdict": "untested",
        "source": "demo",
        "summary_text": "当前结果来自预计算指标的演示级稳健性摘要，不代表完整实时压力测试。",
        "total": len(test_results),
        "passed": sum(1 for r in test_results if r["verdict"] == "pass"),
        "warned": sum(1 for r in test_results if r["verdict"] == "warn"),
        "failed": sum(1 for r in test_results if r["verdict"] == "fail"),
        "untested": sum(1 for r in test_results if r["verdict"] == "untested"),
        "mean_retention": None,
    }
    return test_results, summary


def render():
    """渲染压力测试页面"""
    # 从 session_state 获取因子信息
    factor_id = st.session_state.get("selected_factor_id")
    if factor_id is None:
        st.warning("⚠️ 未选择因子，请先在因子输入页面选择因子。")
        st.stop()

    factor_name = st.session_state.get("selected_factor_name", st.session_state.get("factor_name", "未命名因子"))
    is_demo_c = st.session_state.get("is_demo", False) and factor_id == "R072"

    st.title(f"{factor_name} · 压力测试")

    # Demo C 提示
    if is_demo_c:
        st.info("🧪 **Demo C: 小微盘暴露检查** — 使用 R072 展示剔除微盘和市值中性化测试；只有实时数据计算出的结果才计入鉴证证据。")
        st.session_state["is_demo"] = False

    # 筛选器（使用 radio 避免按钮状态丢失）
    current_filter = st.radio(
        "测试类型筛选",
        options=["全部", "时间", "暴露", "样本"],
        horizontal=True,
        key="stress_filter",
    )

    # ============================================================
    # 缓存检查：避免重复计算
    # ============================================================
    forward_period = int(st.session_state.get("forward_period", 5))
    cache_context = build_cache_context(st.session_state, forward_period=forward_period)
    cache_key = contextual_cache_key("stress", cache_context)
    cached = st.session_state.get(cache_key)

    if cached is not None:
        st.info("📦 使用缓存数据（无需重新计算）")
        results = cached["results"]
        summary = cached["summary"]
    elif isinstance(st.session_state.get("audit_results", {}).get("stress_test"), dict):
        stress_state = st.session_state["audit_results"]["stress_test"]
        if stress_state.get("test_results"):
            st.info("📦 使用鉴证流程中的压力测试结果")
            results = stress_state["test_results"]
            summary = stress_state.get("summary", summarize_stress_results(results))
        else:
            eval_results = st.session_state.get("audit_results", {}).get("traditional_eval", st.session_state.get("eval_results", {}))
            results, summary = _build_fallback_stress_from_eval(eval_results)
            st.warning("⚠️ 当前未执行实时压力测试，已切换为预计算演示摘要。")
    else:
        # 尝试加载对齐数据（带进度提示）
        with st.spinner("正在加载和计算因子数据..."):
            aligned_df = load_aligned_data(st.session_state, forward_period)
        ohlcv_df = st.session_state.get("ohlcv_df")

        # 数据检查
        if aligned_df is None or aligned_df.empty:
            eval_results = st.session_state.get("audit_results", {}).get("traditional_eval", st.session_state.get("eval_results", {}))
            if eval_results:
                results, summary = _build_fallback_stress_from_eval(eval_results)
                st.warning("⚠️ 未找到实时对齐数据，已切换为预计算演示摘要。")
            else:
                st.warning(f"⚠️ 因子数据加载失败（factor_id: {factor_id}），请检查数据是否完整。")
                return

        # 执行压力测试
        if aligned_df is not None and not aligned_df.empty:
            with st.spinner("正在执行压力测试..."):
                results = run_stress_tests(aligned_df, ohlcv_df)
                summary = summarize_stress_results(results)

        # 缓存计算结果
        st.session_state[cache_key] = {
            "context": cache_context,
            "results": results,
            "summary": summary,
        }
        # 保存运行记录到工作台
        save_run(factor_name, factor_id, summary.get("overall_verdict", "untested"),
                 summary.get("summary_text", ""), st.session_state)

    stress_bundle = {
        "test_results": results,
        "summary": summary,
        "source": summary.get("source", "computed"),
    }
    set_audit_result(st.session_state, "stress_test", stress_bundle)

    # 按筛选条件过滤
    if current_filter == "时间":
        filtered_results = [r for r in results if r["test_name"] == "data_delay"]
    elif current_filter == "暴露":
        filtered_results = [r for r in results if r["test_name"] in ("market_cap_neutralize",)]
    elif current_filter == "样本":
        filtered_results = [r for r in results if r["test_name"] in ("remove_micro_cap", "remove_extreme")]
    else:
        filtered_results = results

    if not filtered_results:
        st.info("当前筛选条件下无测试结果。")
        return

    # 构建表格数据
    table_data = []
    for r in filtered_results:
        baseline = r["baseline_rank_ic"]
        stress = r["stress_rank_ic"]
        change = stress - baseline if stress is not None else None
        table_data.append({
            "测试名称": r["test_name_cn"],
            "基线 RankIC": baseline,
            "压力后 RankIC": stress,
            "变化": change,
            "保留比例": r["retention_ratio"],
            "方向保持": "未测试" if r["direction_kept"] is None else ("是" if r["direction_kept"] else "否"),
            "状态": r["verdict"],
            "证据解释": r["evidence"],
        })

    df = pd.DataFrame(table_data)

    # 配置表格列定义
    verdict_color_map = {
        "pass": COLOR_PASS,
        "warn": COLOR_WARN,
        "fail": COLOR_FAIL,
    }

    column_config = {
        "测试名称": st.column_config.TextColumn("测试名称", width="medium"),
        "基线 RankIC": st.column_config.NumberColumn("基线 RankIC", format="%.4f"),
        "压力后 RankIC": st.column_config.NumberColumn("压力后 RankIC", format="%.4f"),
        "变化": st.column_config.NumberColumn("变化", format="%.4f"),
        "保留比例": st.column_config.ProgressColumn(
            "保留比例",
            format="%.1f%%",
            min_value=0.0,
            max_value=1.0,
        ),
        "方向保持": st.column_config.TextColumn("方向保持", width="small"),
        "状态": st.column_config.TextColumn("状态", width="small"),
        "证据解释": st.column_config.TextColumn("证据解释", width="large"),
    }

    st.dataframe(
        df,
        column_config=column_config,
        width='stretch',
        hide_index=True,
    )

    # 在表格下方用 HTML 方式显示状态标签（带颜色）
    st.markdown("### 测试详情")
    for _, row in df.iterrows():
        verdict = row["状态"]
        color = verdict_color_map.get(verdict, COLOR_UNTESTED)
        label_map = {"pass": "通过", "warn": "警告", "fail": "未通过", "untested": "未测试"}
        label = label_map.get(verdict, verdict)

        col1, col2 = st.columns([1, 4])
        with col1:
            st.markdown(
                f'<div style="background:{color};color:white;padding:4px 12px;'
                f'border-radius:4px;font-size:14px;font-weight:bold;text-align:center;'
                f'display:inline-block;min-width:60px">{label}</div>',
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(f"**{row['测试名称']}**")
            st.caption(row["证据解释"])
        st.markdown("---")

    # 结论摘要
    st.markdown("### 总体结论")
    overall = summary["overall_verdict"]
    verdict_color = get_verdict_color(overall)
    verdict_label_map = {
        "pass": "通过",
        "warn": "警告",
        "fragile": "脆弱",
        "invalid": "无效",
        "untested": "未测试",
    }
    verdict_label = verdict_label_map.get(overall, overall)

    col1, col2 = st.columns([1, 3])
    with col1:
        st.markdown(
            f'<div style="background:{verdict_color};color:white;padding:12px 24px;'
            f'border-radius:8px;font-size:20px;font-weight:bold;text-align:center;'
            f'display:inline-block">{verdict_label}</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(f"**{summary['summary_text']}**")

    # 统计卡片
    st.markdown("### 测试统计")
    stat_cols = st.columns(4)
    with stat_cols[0]:
        st.metric("测试总数", summary["total"])
    with stat_cols[1]:
        st.metric("通过", summary["passed"], delta=None)
    with stat_cols[2]:
        st.metric("警告", summary["warned"], delta=None)
    with stat_cols[3]:
        st.metric("未通过", summary["failed"], delta=None)

    mean_retention = summary.get("mean_retention")
    st.metric("平均 RankIC 保留比例", "未测试" if mean_retention is None else f"{mean_retention:.1%}")


if __name__ == "__main__":
    render()
