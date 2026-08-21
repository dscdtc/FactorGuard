"""
FactorGuard 因子验真台 — Streamlit 主入口
"""
import streamlit as st

st.set_page_config(
    page_title="FactorGuard 因子验真台",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 全局状态初始化 ──
if "market" not in st.session_state:
    st.session_state.market = "A股"
if "time_range" not in st.session_state:
    st.session_state.time_range = "全量"
if "selected_factor" not in st.session_state:
    st.session_state.selected_factor = None
if "selected_factor_id" not in st.session_state:
    st.session_state.selected_factor_id = None
if "audit_run_id" not in st.session_state:
    st.session_state.audit_run_id = None
if "factors_loaded" not in st.session_state:
    st.session_state.factors_loaded = False
if "recent_runs" not in st.session_state:
    st.session_state.recent_runs = []

# ── 启动时自动加载因子库 ──
if not st.session_state.factors_loaded:
    with st.spinner("正在加载因子库..."):
        try:
            from engine.factor_loader import init_db, load_all_factors
            from config import FACTORS_DIR
            init_db()
            st.session_state.all_factors = load_all_factors(FACTORS_DIR)
            st.session_state.factors_loaded = True
        except Exception as e:
            st.error(f"因子库加载失败: {e}")
            st.session_state.all_factors = []
            st.session_state.factors_loaded = True

# ── 侧边栏 ──
with st.sidebar:
    st.markdown("## 🔬 FactorGuard")
    st.markdown("*因子验真台*")
    st.divider()

    # 市场选择器
    st.markdown("### 市场")
    market_options = [
        "A股",
        "港股 (即将支持)",
        "美股 (即将支持)",
        "加密货币 (即将支持)",
        "外汇 (即将支持)",
    ]
    selected_market = st.selectbox(
        "选择市场",
        market_options,
        index=0,
        label_visibility="collapsed",
    )
    if selected_market != "A股":
        st.toast("🚧 即将支持")
        st.session_state.market = "A股"
    else:
        st.session_state.market = selected_market

    # 时间范围
    st.markdown("### 时间范围")
    time_options = ["全量 (2019-2026)", "近3年", "近5年", "自定义..."]
    selected_time = st.selectbox(
        "选择时间范围",
        time_options,
        index=0,
        label_visibility="collapsed",
    )
    st.session_state.time_range = selected_time

    st.divider()

    # 内置因子库
    st.markdown("### 内置因子库")
    if st.session_state.get("all_factors"):
        from collections import defaultdict
        factors_by_category = defaultdict(list)
        for f in st.session_state.all_factors:
            factors_by_category[f.category if hasattr(f, 'category') else '其他'].append(f)

        for category, factors in factors_by_category.items():
            with st.expander(f"{category} ({len(factors)})"):
                for f in factors[:5]:  # 每类最多显示5个
                    st.markdown(f"- {f.name_cn}")
                if len(factors) > 5:
                    st.markdown(f"*...还有 {len(factors) - 5} 个因子*")
    else:
        st.markdown("*暂无因子数据*")

    st.divider()

    # 因子导入
    st.markdown("### 因子导入")
    st.markdown("- 📝 文本描述")
    st.markdown("- 🔢 受限公式")
    st.markdown("- 📤 上传因子值")
    st.markdown("- 🐍 Python脚本 *(即将支持)*")

    st.divider()
    st.markdown("*研究质量基础设施*")
    st.markdown("*不输出交易信号*")

# ── 主内容区 ──
st.title("🔬 FactorGuard 因子验真台")
st.markdown("*研究质量基础设施 — 不输出交易信号*")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("内置因子", len(st.session_state.get("all_factors", [])) if st.session_state.get("all_factors") else 0)
with col2:
    st.metric("市场", st.session_state.market)
with col3:
    st.metric("时间范围", st.session_state.time_range)

st.info(
    "👈 请使用左侧导航栏进入各功能页面，或点击下方按钮开始鉴证。\n\n"
    "**页面导航：** 工作台 → 因子输入 → 传统评估 → 压力测试 → 重复检测 → 适用性地图 → 大师方法 → 报告凭证"
)