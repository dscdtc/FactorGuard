"""
FactorGuard 工作台首页
"""
import streamlit as st
from datetime import datetime

from config import COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL
from ui.color_utils import get_verdict_color


def init_session():
    """初始化 session_state"""
    defaults = {
        "recent_runs": [],
        "data_snapshot": None,
        "all_factors": [],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def render_data_snapshot():
    """渲染数据快照状态"""
    st.subheader("📊 数据快照")
    snapshot = st.session_state.get("data_snapshot")

    if snapshot is None:
        # 默认展示静态信息
        cols = st.columns(4)
        with cols[0]:
            st.metric("日期范围", "2020-01-02 ~ 2025-12-31")
        with cols[1]:
            st.metric("股票数量", "5,284")
        with cols[2]:
            st.metric("内置因子", "180+")
        with cols[3]:
            st.metric("数据状态", "✅ 就绪", delta="A股")
    else:
        cols = st.columns(4)
        with cols[0]:
            st.metric("日期范围", snapshot.get("date_range", "N/A"))
        with cols[1]:
            st.metric("股票数量", snapshot.get("stock_count", "N/A"))
        with cols[2]:
            st.metric("因子数量", snapshot.get("factor_count", "N/A"))
        with cols[3]:
            st.metric("数据状态", snapshot.get("status", "N/A"))


def render_recent_runs():
    """渲染最近运行列表"""
    st.subheader("📋 最近运行")

    runs = st.session_state.get("recent_runs", [])
    if not runs:
        st.info("暂无运行记录，点击上方按钮新建鉴证。")
        return

    for run in runs:
        verdict = run.get("verdict", "unknown")
        verdict_color = get_verdict_color(verdict)
        verdict_labels = {
            "invalid": "无效",
            "insufficient": "证据不足",
            "fragile": "脆弱",
            "conditional": "条件有效",
            "supported": "当前支持",
        }
        verdict_label = verdict_labels.get(verdict, verdict)

        with st.container():
            c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
            with c1:
                st.markdown(f"**{run.get('name', '未知因子')}**")
            with c2:
                st.caption(run.get("run_time", "未知时间"))
            with c3:
                st.markdown(
                    f'<span style="color:{verdict_color};font-weight:bold;">{verdict_label}</span>',
                    unsafe_allow_html=True,
                )
            with c4:
                risk_summary = run.get("risk_summary", "")
                if risk_summary:
                    st.caption(risk_summary)
            st.divider()


def render_demo_cards():
    """渲染 Demo 入口卡片"""
    st.subheader("🧪 Demo 快速体验")

    demos = [
        {
            "title": "Demo A: 未来函数因子",
            "desc": '检测使用未来数据的因子，结论应为"无效"',
            "icon": "⏰",
            "factor_id": "demo_future_leak",
            "target_page": "pages/09_鉴证运行.py",
        },
        {
            "title": "Demo B: 重复因子",
            "desc": "发现两个几乎相同的因子，展示三层证据",
            "icon": "🔄",
            "factor_id": "demo_duplicate",
            "target_page": "pages/05_重复性检测.py",
        },
        {
            "title": "Demo C: 小微盘暴露",
            "desc": "揭示因子收益主要来自小盘股暴露",
            "icon": "📉",
            "factor_id": "R072",  # 使用 R072 真实因子，压力测试展示小微盘暴露
            "target_page": "pages/04_压力测试.py",
        },
        {
            "title": "Demo D: 大师方法",
            "desc": "巴菲特质量框架的因子化验证",
            "icon": "🏆",
            "factor_id": "demo_buffett",
            "target_page": "pages/07_大师方法拆解.py",
        },
    ]

    cols = st.columns(4)
    for i, demo in enumerate(demos):
        with cols[i]:
            with st.container(border=True):
                st.markdown(f"**{demo['icon']} {demo['title']}**")
                st.caption(demo['desc'])
                if st.button("运行", key=f"demo_btn_{i}", type="primary", width='stretch'):
                    # 初始化 Demo 数据到 session_state
                    from engine.demo_data import init_demo_session_state
                    init_demo_session_state()

                    st.session_state["selected_factor_id"] = demo["factor_id"]
                    st.session_state["selected_factor_name"] = demo["title"]
                    st.session_state["is_demo"] = True

                    st.switch_page(demo["target_page"])


def main():
    st.set_page_config(page_title="FactorGuard 工作台", page_icon="🔬", layout="wide")
    init_session()

    # === 市场切换器 ===
    col_market, col_title = st.columns([1, 4])
    with col_market:
        market_options = {
            "A股": True,
            "港股": False,
            "美股": False,
            "加密货币": False,
            "外汇": False,
        }
        market = st.selectbox(
            "市场",
            options=list(market_options.keys()),
            index=0,
            key="market_selector",
        )
        st.session_state["current_market"] = market

    with col_title:
        st.title("🔬 FactorGuard 因子验真台")
        st.markdown("*研究质量基础设施 — 不输出交易信号*")

    st.divider()

    # 非 A 股市场显示引导占位
    if market != "A股":
        st.info(f"🚧 **{market}** 市场即将支持。当前仅展示 A 股数据。")
        st.markdown("""
        该市场计划支持以下数据类型：
        - 日线行情数据（OHLCV）
        - 市值与流动性指标
        - 行业与板块分类
        """)
        st.divider()

    if st.button("🚀 新建鉴证", type="primary", width='stretch'):
        st.switch_page("pages/02_因子输入.py")

    st.divider()

    render_recent_runs()
    st.divider()
    render_demo_cards()
    st.divider()
    render_data_snapshot()


if __name__ == "__main__":
    main()