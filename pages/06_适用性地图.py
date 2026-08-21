"""
FactorGuard 适用性地图页面
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import PLOTLY_TEMPLATE, CHART_HEIGHT
from engine.suitability import compute_suitability_map
from engine.factor_computer import load_aligned_data
from engine.run_recorder import save_run
from ui.color_utils import get_heatmap_colorscale, COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL, COLOR_UNTESTED
from ui.chart_utils import create_heatmap


def init_session():
    defaults = {
        "aligned_data": None,
        "suitability_result": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def render_suitability_heatmap(result):
    """渲染适用性热力图"""
    matrix = result["matrix"]
    dim1_vals = result["dim1_values"]
    dim2_vals = result["dim2_values"]
    dim1_name = result["dim1_name"]
    dim2_name = result["dim2_name"]

    if not matrix or not dim1_vals or not dim2_vals:
        st.warning("数据不足，无法生成适用性地图。")
        return

    # 提取 RankIC 矩阵和注释矩阵
    ic_matrix = [[cell["rank_ic"] for cell in row] for row in matrix]
    sample_counts = [[cell["sample_count"] for cell in row] for row in matrix]
    direction_flipped = [[cell["direction_flipped"] for cell in row] for row in matrix]
    evidence_levels = [[cell["evidence_level"] for cell in row] for row in matrix]

    # 构建 hover 文本
    hover_text = []
    for i, row in enumerate(matrix):
        hover_row = []
        for j, cell in enumerate(row):
            parts = [
                f"{dim1_name}: {dim1_vals[i]}",
                f"{dim2_name}: {dim2_vals[j]}",
                f"RankIC: {cell['rank_ic']:.4f}",
                f"样本数: {cell['sample_count']}",
                f"证据等级: {cell['evidence_level']}",
            ]
            if cell["direction_flipped"]:
                parts.append("⚠️ 方向翻转")
            hover_row.append("<br>".join(parts))
        hover_text.append(hover_row)

    # 创建热力图
    fig = go.Figure(data=go.Heatmap(
        z=ic_matrix,
        x=dim2_vals,
        y=dim1_vals,
        colorscale=get_heatmap_colorscale(),
        zmid=0,
        text=hover_text,
        hoverinfo="text",
        hovertemplate="%{text}<extra></extra>",
        showscale=True,
        colorbar=dict(title="RankIC"),
    ))

    # 为 direction_flipped 的单元格添加红色边框标记
    for i, row in enumerate(matrix):
        for j, cell in enumerate(row):
            if cell["direction_flipped"]:
                fig.add_shape(
                    type="rect",
                    x0=j - 0.5, x1=j + 0.5,
                    y0=i - 0.5, y1=i + 0.5,
                    line=dict(color=COLOR_FAIL, width=3),
                    fillcolor="rgba(0,0,0,0)",
                )

    fig.update_layout(
        title=f"{dim1_name} × {dim2_name} 适用性矩阵",
        xaxis_title=dim2_name,
        yaxis_title=dim1_name,
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT + 100,
        margin=dict(l=80, r=40, t=50, b=40),
    )

    st.plotly_chart(fig, width='stretch')

    # 图例说明
    st.markdown("#### 图例说明")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f'<span style="color:{COLOR_PASS};">●</span> 正相关（绿）', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<span style="color:{COLOR_WARN};">●</span> 弱正相关（黄）', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<span style="color:{COLOR_UNTESTED};">●</span> 中性（灰）', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<span style="color:{COLOR_NEUTRAL};">●</span> 弱负相关（蓝）', unsafe_allow_html=True)
    with c5:
        st.markdown(f'<span style="color:{COLOR_FAIL};">■</span> 方向翻转（红框）', unsafe_allow_html=True)


def render_sample_table(result):
    """渲染样本量表格"""
    matrix = result["matrix"]
    dim1_vals = result["dim1_values"]
    dim2_vals = result["dim2_values"]
    dim1_name = result["dim1_name"]
    dim2_name = result["dim2_name"]

    if not matrix:
        return

    st.markdown("#### 样本量分布")

    header = [f"{dim1_name}\\{dim2_name}"] + dim2_vals
    rows = []
    for i, row in enumerate(matrix):
        rows.append([dim1_vals[i]] + [str(cell["sample_count"]) for cell in row])

    df = pd.DataFrame(rows, columns=header)
    st.dataframe(df.set_index(header[0]), width='stretch')


def render_evidence_table(result):
    """渲染证据等级表格"""
    matrix = result["matrix"]
    dim1_vals = result["dim1_values"]
    dim2_vals = result["dim2_values"]
    dim1_name = result["dim1_name"]
    dim2_name = result["dim2_name"]

    if not matrix:
        return

    st.markdown("#### 证据等级分布")

    level_labels = {"good": "充足", "mid": "中等", "weak": "偏少", "na": "无"}
    level_colors = {"good": COLOR_PASS, "mid": COLOR_NEUTRAL, "weak": COLOR_WARN, "na": COLOR_UNTESTED}

    header = [f"{dim1_name}\\{dim2_name}"] + dim2_vals
    rows = []
    for i, row in enumerate(matrix):
        row_vals = [dim1_vals[i]]
        for cell in row:
            level = cell["evidence_level"]
            label = level_labels.get(level, level)
            color = level_colors.get(level, COLOR_UNTESTED)
            row_vals.append(f'<span style="color:{color};font-weight:bold;">{label}</span>')
        rows.append(row_vals)

    df = pd.DataFrame(rows, columns=header)
    st.markdown(df.set_index(header[0]).to_html(escape=False), unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="FactorGuard 适用性地图", page_icon="🗺️", layout="wide")
    init_session()

    # 检查因子选择
    factor_id = st.session_state.get("selected_factor_id")
    if factor_id is None:
        st.warning("⚠️ 未选择因子，请先在因子输入页面选择因子。")
        st.stop()

    st.title("🗺️ 因子适用性地图")
    st.markdown("*分析因子在不同市场环境下的预测能力差异*")

    st.divider()

    # 维度选择器
    dim_options = {
        "market_cap": "市值",
        "volatility": "波动率",
        "style": "成长价值",
        "liquidity": "流动性",
        "time": "时间",
    }

    c1, c2 = st.columns(2)
    with c1:
        dim1_key = st.selectbox(
            "主维度（行）",
            options=list(dim_options.keys()),
            format_func=lambda x: dim_options[x],
            index=0,
            key="dim1_select",
        )
    with c2:
        dim2_key = st.selectbox(
            "次维度（列）",
            options=list(dim_options.keys()),
            format_func=lambda x: dim_options[x],
            index=1,
            key="dim2_select",
        )

    st.divider()

    # ============================================================
    # 缓存检查：避免重复计算
    # ============================================================
    cache_key = f"suitability_{factor_id}_{dim1_key}_{dim2_key}"
    cached = st.session_state.get(cache_key)

    if cached is not None:
        st.info("📦 使用缓存数据（无需重新计算）")
        result = cached
    else:
        # 加载数据
        with st.spinner("正在加载和计算因子数据..."):
            aligned_df = load_aligned_data(st.session_state)

        if aligned_df is None:
            st.warning(f"⚠️ 因子数据加载失败（factor_id: {factor_id}），请检查数据是否完整。")
            st.info("""
            **使用步骤：**
            1. 前往 **因子输入** 页面选择或上传因子
            2. 完成因子评估，生成对齐数据
            3. 返回本页面查看适用性地图
            """)
            return

        # 计算适用性
        with st.spinner("正在计算适用性地图..."):
            try:
                result = compute_suitability_map(
                    aligned_df,
                    dim1=dim1_key,
                    dim2=dim2_key,
                )
                st.session_state["suitability_result"] = result
            except Exception as e:
                st.error(f"计算失败: {e}")
                return

        # 缓存计算结果
        st.session_state[cache_key] = result

        # 保存运行记录到工作台
        factor_name = st.session_state.get("selected_factor_name", factor_id)
        assessment = result.get("overall_assessment", "")
        # 从评估文本推断裁决
        if "有效" in assessment or "显著" in assessment:
            suit_verdict = "supported"
        elif "弱" in assessment or "不稳定" in assessment:
            suit_verdict = "fragile"
        else:
            suit_verdict = "conditional"
        save_run(factor_name, factor_id, suit_verdict,
                 assessment[:120] if assessment else "适用性分析完成", st.session_state)

    # 渲染热力图
    render_suitability_heatmap(result)

    st.divider()

    # 总体评估
    st.markdown("#### 📋 总体评估")
    st.markdown(result["overall_assessment"])

    st.divider()

    # 详细表格
    tab1, tab2 = st.tabs(["📊 样本量", "🔬 证据等级"])

    with tab1:
        render_sample_table(result)

    with tab2:
        render_evidence_table(result)


if __name__ == "__main__":
    main()