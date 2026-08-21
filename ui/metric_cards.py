"""
指标卡片组件（Streamlit 原生渲染）
"""
import streamlit as st


def render_metric_card(label: str, value: str, delta: str = None,
                       delta_color: str = "normal", help_text: str = None):
    """渲染单指标卡片"""
    st.metric(label=label, value=value, delta=delta,
              delta_color=delta_color, help=help_text)


def render_metric_row(metrics: list[dict]):
    """渲染一行指标卡片，metrics 每项包含 label/value/delta 等"""
    cols = st.columns(len(metrics))
    for i, m in enumerate(metrics):
        with cols[i]:
            render_metric_card(**m)


def render_verdict_badge(verdict: str):
    """渲染结论徽章，大号文字+背景色"""
    color_map = {
        "invalid": "#a53c3c",
        "insufficient": "#d49b2e",
        "fragile": "#d49b2e",
        "conditional": "#2267a5",
        "supported": "#176c49"
    }
    label_map = {
        "invalid": "无效",
        "insufficient": "证据不足",
        "fragile": "脆弱",
        "conditional": "条件有效",
        "supported": "当前支持"
    }
    color = color_map.get(verdict, "#b8c2ca")
    label = label_map.get(verdict, verdict)
    st.markdown(
        f'<div style="background:{color};color:white;padding:12px 24px;'
        f'border-radius:8px;font-size:24px;font-weight:bold;text-align:center;'
        f'display:inline-block">{label}</div>',
        unsafe_allow_html=True
    )