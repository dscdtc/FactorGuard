"""
压力测试页面 - 因子对抗式压力测试结果展示
"""

import streamlit as st
import pandas as pd
import numpy as np

from engine.stress_test import run_stress_tests, summarize_stress_results
from engine.factor_computer import load_aligned_data
from engine.run_recorder import save_run
from ui.metric_cards import render_verdict_badge
from ui.color_utils import get_verdict_color
from config import COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL, COLOR_UNTESTED

st.set_page_config(page_title="压力测试", page_icon="💪", layout="wide")


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
        st.info("🧪 **Demo C: 小微盘暴露因子** — R072 原始 RankIC 较好，但剔除微盘后 RankIC 保留率仅 25%，暴露严重小微盘依赖。")
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
    cache_key = f"stress_{factor_id}"
    cached = st.session_state.get(cache_key)

    if cached is not None:
        st.info("📦 使用缓存数据（无需重新计算）")
        results = cached["results"]
        summary = cached["summary"]
    else:
        # 尝试加载对齐数据（带进度提示）
        with st.spinner("正在加载和计算因子数据..."):
            aligned_df = load_aligned_data(st.session_state)
        ohlcv_df = st.session_state.get("ohlcv_df")

        # 数据检查
        if aligned_df is None or aligned_df.empty:
            st.warning(f"⚠️ 因子数据加载失败（factor_id: {factor_id}），请检查数据是否完整。")
            return

        # 执行压力测试
        with st.spinner("正在执行压力测试..."):
            results = run_stress_tests(aligned_df, ohlcv_df)
            summary = summarize_stress_results(results)

        # 缓存计算结果
        st.session_state[cache_key] = {
            "results": results,
            "summary": summary,
        }

        # 保存运行记录到工作台
        save_run(factor_name, factor_id, summary.get("overall_verdict", "untested"),
                 summary.get("summary_text", ""), st.session_state)

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
        change = stress - baseline
        table_data.append({
            "测试名称": r["test_name_cn"],
            "基线 RankIC": baseline,
            "压力后 RankIC": stress,
            "变化": change,
            "保留比例": r["retention_ratio"],
            "方向保持": "是" if r["direction_kept"] else "否",
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
        label_map = {"pass": "通过", "warn": "警告", "fail": "未通过"}
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

    st.metric("平均 RankIC 保留比例", f"{summary['mean_retention']:.1%}")


if __name__ == "__main__":
    render()