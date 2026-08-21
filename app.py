"""
FactorGuard 因子验真台 — Streamlit 主入口
"""
import json

import streamlit as st

from config import BASIC_PARQUET, DATA_LOCAL, OHLCV_PARQUET, SNAPSHOT_MANIFEST
from engine.factor_loader import get_factor_by_id
from engine.session_context import select_factor
from models.factor_spec import FactorSpec
from ui.color_utils import get_verdict_color

st.set_page_config(
    page_title="FactorGuard 因子验真台",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def snapshot_range_label() -> str:
    """Read the user-facing sample range from the frozen snapshot manifest."""
    try:
        manifest = json.loads(SNAPSHOT_MANIFEST.read_text(encoding="utf-8"))
        start = manifest.get("date_start")
        end = manifest.get("date_end")
        if start and end:
            return f"比赛快照（{start} 至 {end}）"
    except (OSError, ValueError, TypeError):
        pass
    return "当前 Parquet 快照"


def load_snapshot_manifest() -> dict:
    """Load the frozen snapshot metadata used by the homepage."""
    try:
        return json.loads(SNAPSHOT_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def render_data_snapshot() -> None:
    """Render the portable competition snapshot status."""
    manifest = load_snapshot_manifest()
    snapshot_ready = OHLCV_PARQUET.exists() and BASIC_PARQUET.exists()
    source_ready = DATA_LOCAL.exists()
    start = manifest.get("date_start")
    end = manifest.get("date_end")
    date_range = f"{start} 至 {end}" if start and end else "未记录"
    stocks = manifest.get("stocks")
    rows = manifest.get("rows")

    st.subheader("数据快照")
    cols = st.columns(4)
    with cols[0]:
        st.metric("行情快照", "已就绪" if snapshot_ready else "缺失")
    with cols[1]:
        st.metric("样本区间", date_range)
    with cols[2]:
        st.metric("覆盖股票", f"{stocks:,} 只" if isinstance(stocks, int) else "未记录")
    with cols[3]:
        st.metric("样本行数", f"{rows:,}" if isinstance(rows, int) else "未记录")

    if snapshot_ready and not source_ready:
        st.caption("正式快照可独立运行；只有重建快照时才需要原始 CSV 数据源。")
    elif not snapshot_ready and source_ready:
        st.warning("已发现原始数据，但正式 Parquet 快照缺失。请先显式运行快照构建脚本。")
    elif not snapshot_ready:
        st.warning("正式快照和原始数据源均不可用，目前只能查看历史预计算摘要。")


def render_recent_runs() -> None:
    """Render the latest deterministic audit outcomes from this session."""
    st.subheader("最近运行")
    runs = st.session_state.get("recent_runs", [])
    if not runs:
        st.info("暂无运行记录。新建鉴证后，正式结论会显示在这里。")
        return

    verdict_labels = {
        "invalid": "无效",
        "insufficient": "证据不足",
        "fragile": "脆弱",
        "conditional": "条件有效",
        "supported": "当前支持",
    }
    for run in runs:
        verdict = run.get("verdict", "unknown")
        cols = st.columns([3, 2, 2, 3])
        with cols[0]:
            st.markdown(f"**{run.get('name', '未知因子')}**")
        with cols[1]:
            st.caption(run.get("run_time", "未知时间"))
        with cols[2]:
            st.markdown(
                f'<span style="color:{get_verdict_color(verdict)};font-weight:700">'
                f'{verdict_labels.get(verdict, verdict)}</span>',
                unsafe_allow_html=True,
            )
        with cols[3]:
            st.caption(run.get("risk_summary", ""))
        st.divider()


def render_demo_entries() -> None:
    """Render the four competition demo entry points."""
    st.subheader("Demo 快速体验")
    demos = [
        {
            "title": "未来函数因子",
            "description": "验证未来数据泄漏必须导致无效结论。",
            "factor_id": "demo_future_leak",
            "target": "pages/09_鉴证运行.py",
        },
        {
            "title": "重复因子",
            "description": "检查公式、暴露和收益序列的重复性。",
            "factor_id": "demo_duplicate",
            "target": "pages/05_重复性检测.py",
        },
        {
            "title": "小微盘暴露",
            "description": "检查收益是否依赖小市值股票暴露。",
            "factor_id": "R072",
            "target": "pages/04_压力测试.py",
        },
        {
            "title": "大师方法",
            "description": "验证公开方法的可计算代理与时点边界。",
            "factor_id": "demo_buffett",
            "target": "pages/07_大师方法拆解.py",
        },
    ]

    cols = st.columns(4)
    for index, demo in enumerate(demos):
        with cols[index]:
            with st.container(border=True):
                st.markdown(f"**{demo['title']}**")
                st.caption(demo["description"])
                if st.button("运行", key=f"home_demo_{index}", width="stretch"):
                    spec = get_factor_by_id(demo["factor_id"])
                    if spec is None:
                        spec = FactorSpec(
                            factor_id=demo["factor_id"],
                            name=demo["factor_id"],
                            name_cn=demo["title"],
                            description=demo["description"],
                            base="return",
                            params={"window": 20},
                            source="demo",
                        )
                    select_factor(st.session_state, spec, is_demo=True)
                    st.switch_page(demo["target"])


SNAPSHOT_RANGE_LABEL = snapshot_range_label()

# ── 全局状态初始化 ──
if "market" not in st.session_state:
    st.session_state.market = "A股"
if "time_range" not in st.session_state:
    st.session_state.time_range = SNAPSHOT_RANGE_LABEL
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
            from engine.factor_loader import get_all_factors

            factors = get_all_factors()
            st.session_state.all_factors = factors
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

    # 全局仅展示正式快照范围；细分筛选在传统评估页执行。
    st.markdown("### 数据范围")
    st.caption(SNAPSHOT_RANGE_LABEL)
    st.session_state.time_range = SNAPSHOT_RANGE_LABEL

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
    st.caption("安全边界：不执行用户上传的 Python 脚本")

    st.divider()
    st.markdown("*研究质量基础设施*")
    st.markdown("*不输出交易信号*")

def render_home() -> None:
    """Render the single homepage replacing the former workbench page."""
    st.title("🔬 FactorGuard 因子验真台")
    st.markdown("*研究质量基础设施 — 不输出交易信号*")

    if st.button("新建鉴证", type="primary", width="stretch"):
        st.switch_page("pages/02_因子输入.py")

    st.divider()
    render_data_snapshot()
    st.divider()
    render_recent_runs()
    st.divider()
    render_demo_entries()


navigation = st.navigation(
    {
        "研究工作流": [
            st.Page(render_home, title="首页", icon="🏠", default=True),
            st.Page("pages/02_因子输入.py", title="因子输入", icon="📥"),
            st.Page("pages/03_传统评估.py", title="传统评估", icon="🔍"),
            st.Page("pages/04_压力测试.py", title="压力测试", icon="💪"),
            st.Page("pages/05_重复性检测.py", title="重复性检测", icon="🔗"),
            st.Page("pages/06_适用性地图.py", title="适用性地图", icon="📊"),
            st.Page("pages/07_大师方法拆解.py", title="大师方法拆解", icon="👨‍🏫"),
            st.Page("pages/08_报告与凭证.py", title="报告与凭证", icon="🧾"),
            st.Page("pages/09_鉴证运行.py", title="鉴证运行", icon="🧪"),
        ]
    },
    position="sidebar",
    expanded=True,
)
navigation.run()
