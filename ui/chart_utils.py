"""
Plotly 图表工厂
"""
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from config import PLOTLY_TEMPLATE, CHART_HEIGHT


def create_rolling_ic_chart(dates, rolling_rank_ic, title="滚动 RankIC"):
    """创建滚动 RankIC 折线图，y=0 处添加虚线参考线"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates,
        y=rolling_rank_ic,
        mode="lines",
        name="RankIC",
        line=dict(color="#2267a5", width=2),
        fill="tozeroy",
        fillcolor="rgba(34, 103, 165, 0.1)"
    ))
    fig.add_hline(
        y=0, line_dash="dash", line_color="#b8c2ca",
        line_width=1, annotation_text="y=0",
        annotation_position="bottom right"
    )
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="RankIC",
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        hovermode="x unified"
    )
    return fig


def create_group_return_chart(groups, returns, title="分组收益"):
    """创建分组收益柱状图"""
    colors = [
        "#a53c3c", "#d49b2e", "#b8c2ca", "#2267a5", "#176c49"
    ]
    bar_colors = []
    for i, r in enumerate(returns):
        if r < 0:
            bar_colors.append(colors[0] if i < len(colors) else "#a53c3c")
        elif r == 0:
            bar_colors.append(colors[2] if 2 < len(colors) else "#b8c2ca")
        else:
            bar_colors.append(colors[-1] if i < len(colors) else "#176c49")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=groups,
        y=returns,
        marker_color=bar_colors,
        text=[f"{v:.4f}" for v in returns],
        textposition="outside",
        textfont=dict(color="#333333", size=10)
    ))
    fig.add_hline(
        y=0, line_dash="solid", line_color="#b8c2ca",
        line_width=1
    )
    fig.update_layout(
        title=title,
        xaxis_title="分组",
        yaxis_title="收益",
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        showlegend=False
    )
    return fig


def create_cumulative_return_chart(dates, cumulative_returns, labels, title="累计收益"):
    """创建分组累计收益曲线"""
    colors = px.colors.qualitative.Set2
    fig = go.Figure()
    for i, cum_ret in enumerate(cumulative_returns):
        label = labels[i] if i < len(labels) else f"G{i+1}"
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=dates,
            y=cum_ret,
            mode="lines",
            name=label,
            line=dict(color=color, width=2)
        ))
    fig.add_hline(
        y=0, line_dash="dash", line_color="#b8c2ca",
        line_width=1
    )
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="累计收益",
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig


def create_heatmap(matrix_data, dim1_values, dim2_values, dim1_name, dim2_name, title="适用性地图"):
    """创建热力图"""
    fig = go.Figure(data=go.Heatmap(
        z=matrix_data,
        x=dim2_values,
        y=dim1_values,
        colorscale=[
            [0.0, "#a53c3c"],
            [0.25, "#d49b2e"],
            [0.5, "#b8c2ca"],
            [0.75, "#2267a5"],
            [1.0, "#176c49"]
        ],
        zmid=0,
        text=[[f"{v:.4f}" for v in row] for row in matrix_data],
        texttemplate="%{text}",
        textfont=dict(size=10),
        hovertemplate=f"{dim2_name}: %{{x}}<br>{dim1_name}: %{{y}}<br>值: %{{z:.4f}}<extra></extra>"
    ))
    fig.update_layout(
        title=title,
        xaxis_title=dim2_name,
        yaxis_title=dim1_name,
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        coloraxis_colorbar=dict(title="")
    )
    return fig


def create_radar_chart(categories, values, title="证据雷达"):
    """创建雷达图"""
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=categories,
        fill="toself",
        name="证据强度",
        line=dict(color="#2267a5", width=2),
        fillcolor="rgba(34, 103, 165, 0.25)"
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, max(values) * 1.1 + 0.1] if values else [0, 1],
                showticklabels=False
            )
        ),
        title=title,
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        showlegend=False
    )
    return fig


def create_distribution_chart(factor_values, title="因子值分布"):
    """创建因子值分布直方图"""
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=factor_values,
        nbinsx=50,
        marker_color="#2267a5",
        marker_line_color="white",
        marker_line_width=1,
        opacity=0.85,
        name="频率"
    ))
    fig.add_vline(
        x=0, line_dash="dot", line_color="#b8c2ca",
        line_width=1.5
    )
    fig.update_layout(
        title=title,
        xaxis_title="因子值",
        yaxis_title="频次",
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        showlegend=False
    )
    return fig


def create_coverage_chart(dates, coverage, title="覆盖率时间序列"):
    """创建覆盖率时间序列折线图"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates,
        y=coverage,
        mode="lines",
        name="覆盖率",
        line=dict(color="#2267a5", width=2),
        fill="tozeroy",
        fillcolor="rgba(34, 103, 165, 0.15)"
    ))
    fig.add_hline(
        y=0.8, line_dash="dash", line_color="#176c49",
        line_width=1, annotation_text="80%",
        annotation_position="bottom right"
    )
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="覆盖率",
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        yaxis=dict(range=[0, 1.05]),
        hovermode="x unified"
    )
    return fig


def create_decay_chart(periods, ic_values, title="IC 衰减曲线"):
    """创建预测周期 IC 衰减对比图"""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=periods,
        y=ic_values,
        marker_color="#2267a5",
        text=[f"{v:.4f}" for v in ic_values],
        textposition="outside",
        textfont=dict(color="#333333", size=11)
    ))
    fig.add_hline(
        y=0, line_dash="dash", line_color="#b8c2ca",
        line_width=1
    )
    fig.update_layout(
        title=title,
        xaxis_title="预测周期（交易日）",
        yaxis_title="RankIC Mean",
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        showlegend=False
    )
    return fig


def create_autocorr_chart(lags, autocorr_values, title="因子自相关"):
    """创建因子自相关折线图"""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=lags,
        y=autocorr_values,
        marker_color="#2267a5",
        text=[f"{v:.3f}" for v in autocorr_values],
        textposition="outside",
        textfont=dict(color="#333333", size=9)
    ))
    fig.add_hline(
        y=0, line_dash="dash", line_color="#b8c2ca",
        line_width=1
    )
    fig.update_layout(
        title=title,
        xaxis_title="滞后期（交易日）",
        yaxis_title="自相关系数",
        template=PLOTLY_TEMPLATE,
        height=CHART_HEIGHT,
        margin=dict(l=40, r=40, t=50, b=40),
        showlegend=False
    )
    return fig