"""FactorGuard 因子输入页面 - 4 种安全的因子引入方式。"""
import streamlit as st
import pandas as pd
import re

from config import (
    COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL, DATA_SNAPSHOT,
)
from models.factor_spec import FactorSpec
from engine.factor_loader import get_all_factors, get_precomputed_metrics
from engine.ai_explainer import parse_text_to_spec
from engine.formula_parser import FormulaParser
from engine.session_context import select_factor
from ui.color_utils import get_verdict_color


def init_session():
    """初始化 session_state"""
    defaults = {
        "all_factors": [],
        "selected_factor_id": None,
        "parsed_spec": None,
        "uploaded_df": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _safe_factor_id(prefix: str, name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "_", name).strip("_") or "factor"
    return f"{prefix}_{slug}"[:80]


def _custom_spec(factor_id: str, name_cn: str, formula: str, *, category="其他",
                 direction="higher", params=None, inputs=None, rationale=None) -> FactorSpec:
    parsed = FormulaParser().parse(formula)
    return FactorSpec(
        factor_id=factor_id,
        name=factor_id,
        name_cn=name_cn,
        description=rationale or "用户自定义因子",
        formula=formula,
        formula_cn=rationale,
        expected_direction=direction,
        category=category,
        base="custom_formula",
        params=params or {},
        inputs=inputs or parsed.used_fields,
        min_window=max(1, parsed.max_window),
        source="custom",
        rationale_cn=rationale,
    )


def tab_builtin():
    """标签页 1: 内置因子"""
    st.markdown("### 内置因子库")
    st.markdown("*从预先计算好的因子库中选择因子进行验真*")

    selected_factor_id = st.session_state.get("selected_factor_id")
    selected_factor_name = st.session_state.get("selected_factor_name")
    if selected_factor_id and selected_factor_name:
        with st.container(border=True):
            st.success(f"已选择因子：{selected_factor_name}（{selected_factor_id}）")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🚀 进入传统评估", key="goto_trad_eval", type="primary", width="stretch"):
                    st.switch_page("pages/03_传统评估.py")
            with col_b:
                if st.button("⚙️ 进入鉴证运行", key="goto_audit_run", width="stretch"):
                    st.switch_page("pages/09_鉴证运行.py")
        st.markdown("---")

    # 加载因子列表
    if not st.session_state.get("all_factors"):
        try:
            st.session_state["all_factors"] = get_all_factors()
        except Exception:
            st.session_state["all_factors"] = []

    all_factors = st.session_state["all_factors"]

    if not all_factors:
        st.warning("因子库为空，请先初始化数据。")
        return

    # 搜索和类别筛选同时约束选择器与详情卡片。
    search_query = st.text_input(
        "搜索因子",
        placeholder="输入因子 ID、名称或类别",
        key="builtin_factor_search",
    ).strip().lower()
    categories = sorted(set(f.category for f in all_factors if f.category))
    selected_cats = st.multiselect(
        "按类别筛选",
        options=categories,
        default=[],
        placeholder="全部类别",
    )

    filtered = all_factors
    if selected_cats:
        filtered = [f for f in all_factors if f.category in selected_cats]
    if search_query:
        filtered = [
            factor for factor in filtered
            if search_query in " ".join(
                [
                    factor.factor_id,
                    factor.name_cn,
                    factor.category or "",
                    factor.description or "",
                ]
            ).lower()
        ]

    st.caption(f"共 {len(filtered)} / {len(all_factors)} 个因子")

    if not filtered:
        st.info("没有匹配的因子。")
        return

    st.subheader("快速选择")
    quick_factor = st.selectbox(
        "选择一个内置因子作为当前研究对象",
        options=filtered,
        index=0,
        format_func=lambda f: f"{f.factor_id} - {f.name_cn}",
        key="builtin_quick_factor",
    )
    quick_cols = st.columns(2)
    with quick_cols[0]:
        if st.button("✅ 设为当前因子", key="set_quick_factor", type="primary", width="stretch"):
            select_factor(st.session_state, quick_factor)
            st.success(f"已选择 {quick_factor.name_cn}")
            st.rerun()
    with quick_cols[1]:
        if st.button("🚀 设为当前因子并进入传统评估", key="set_quick_factor_and_go", width="stretch"):
            select_factor(st.session_state, quick_factor)
            st.switch_page("pages/03_传统评估.py")

    st.markdown("---")

    # 详情卡片只渲染首批结果，避免 805 个因子的 N+1 查询和超大页面。
    card_limit = 12
    displayed_factors = filtered[:card_limit]
    if len(filtered) > card_limit:
        st.caption(
            f"当前展示前 {card_limit} 个结果；可通过搜索、类别筛选或上方选择器定位其余因子。"
        )

    # 因子卡片网格：每行 3 列
    cols_per_row = 3
    for i in range(0, len(displayed_factors), cols_per_row):
        row_factors = displayed_factors[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, factor in enumerate(row_factors):
            with cols[j]:
                metrics = {}
                try:
                    metrics = get_precomputed_metrics(factor.factor_id)
                except Exception:
                    pass

                ic_val = metrics.get("ic_mean_5d")
                icir_val = metrics.get("icir_5d")
                coverage_val = metrics.get("coverage")
                turnover_val = metrics.get("turnover")
                status_val = metrics.get("status", "N/A")
                ls_val = metrics.get("long_short_mean_5d")

                direction_label = "做多" if factor.expected_direction == "higher" else "做空"

                # 状态颜色
                status_color = "#4CAF50" if status_val == "pass" else ("#FF9800" if status_val == "warn" else "#F44336")

                with st.container(border=True):
                    # 标题行：名称 + 状态标识
                    st.markdown(
                        f'**{factor.name_cn}** '
                        f'<span style="font-size:10px;color:{status_color}">●</span>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"{factor.category} · {direction_label}")

                    # 预计算指标
                    if metrics:
                        metric_cols = st.columns(2)
                        with metric_cols[0]:
                            if isinstance(ic_val, (int, float)):
                                st.metric("IC Mean", f"{ic_val:.4f}")
                            if isinstance(icir_val, (int, float)):
                                st.metric("ICIR", f"{icir_val:.4f}")
                        with metric_cols[1]:
                            if isinstance(coverage_val, (int, float)):
                                st.metric("覆盖率", f"{coverage_val:.1%}")
                            if isinstance(turnover_val, (int, float)):
                                st.metric("换手率", f"{turnover_val:.1%}")

                    if st.button("选择", key=f"builtin_{factor.factor_id}", type="primary", width="stretch"):
                        select_factor(st.session_state, factor)
                        st.success(f"已选择 {factor.name_cn}，请点击上方按钮继续。")
                        st.rerun()


def tab_text():
    """标签页 2: 文本描述"""
    st.markdown("### 文本描述因子")
    st.markdown("*用自然语言描述因子，由确定性规则解析为结构化定义*")

    text_input = st.text_area(
        "输入因子描述",
        height=150,
        placeholder="例如：20日动量因子，计算过去20个交易日的收益率，做多高收益股票",
        key="text_factor_input",
    )

    if st.button("解析为结构化定义", type="primary", width="stretch"):
        if not text_input.strip():
            st.warning("请输入因子描述文本。")
            return

        with st.spinner("正在解析..."):
            try:
                parsed = parse_text_to_spec(text_input)
                st.session_state["parsed_spec"] = parsed
            except Exception as e:
                st.error(f"解析失败: {e}")
                return

        st.success("解析完成！")

        parsed = st.session_state.get("parsed_spec", {})
        if parsed:
            st.markdown("#### 解析结果")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("因子名称", parsed.get("name_cn", "N/A"))
            with c2:
                st.metric("因子类别", parsed.get("category", "N/A"))
            with c3:
                direction = parsed.get("expected_direction", "higher")
                st.metric("预期方向", "做多" if direction == "higher" else "做空")

            st.markdown("**公式**")
            st.code(parsed.get("formula", "N/A"), language="text")

            st.markdown("**公式描述**")
            st.caption(parsed.get("formula_cn", ""))

            st.markdown("**逻辑依据**")
            st.caption(parsed.get("rationale_cn", ""))

            st.markdown("**参数**")
            st.json(parsed.get("params", {}))

            if st.button("✅ 确认并开始验真", type="primary", width="stretch"):
                factor_id = _safe_factor_id("custom_text", parsed.get("name_cn", "factor"))
                spec = _custom_spec(
                    factor_id, parsed.get("name_cn", "自定义因子"), parsed["formula"],
                    category=parsed.get("category", "其他"),
                    direction=parsed.get("expected_direction", "higher"),
                    params=parsed.get("params", {}), inputs=parsed.get("inputs", []),
                    rationale=parsed.get("rationale_cn"),
                )
                select_factor(st.session_state, spec)
                st.switch_page("pages/03_传统评估.py")


def tab_formula():
    """标签页 3: 受限公式"""
    st.markdown("### 受限公式输入")
    st.markdown("*输入因子计算公式，实时语法检查*")

    field_options = ['open', 'high', 'low', 'close', 'volume', 'amount',
                     'total_mv', 'circ_mv', 'turnover_rate', 'pe_ttm']
    func_options = ['delay', 'ts_mean', 'ts_sum', 'ts_std', 'ts_min', 'ts_max',
                    'rank_cs', 'zscore_cs', 'log', 'abs', 'sign', 'sqrt']

    with st.expander("📖 可用字段与函数", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**可用字段**")
            for f in field_options:
                st.caption(f"`{f}`")
        with c2:
            st.markdown("**可用函数**")
            for f in func_options:
                st.caption(f"`{f}`")

    formula = st.text_input(
        "因子公式",
        placeholder="例如: ts_mean(delay(close, 1) / delay(close, 20) - 1, 5)",
        key="formula_input",
    )

    if formula.strip():
        try:
            parser = FormulaParser()
            result = parser.parse(formula.strip())

            if result.errors:
                for err in result.errors:
                    st.error(f"❌ {err}")

            if result.warnings:
                for warn in result.warnings:
                    st.warning(f"⚠️ {warn}")

            if result.valid and not result.errors:
                st.success("✅ 公式语法正确")
                st.markdown("**解析详情**")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("最大回看窗口", result.max_window)
                with c2:
                    st.metric("使用字段", ", ".join(result.used_fields) if result.used_fields else "无")
                with c3:
                    st.metric("使用函数", ", ".join(result.used_functions) if result.used_functions else "无")

                if st.button("✅ 确认并开始验真", key="formula_confirm", type="primary", width="stretch"):
                    factor_id = _safe_factor_id("custom_formula", formula[:40])
                    spec = _custom_spec(factor_id, "自定义公式因子", formula.strip())
                    select_factor(st.session_state, spec)
                    st.switch_page("pages/03_传统评估.py")
        except Exception as e:
            st.error(f"解析异常: {e}")


def tab_upload():
    """标签页 4: 因子值上传"""
    st.markdown("### 因子值上传")
    st.markdown("*上传 CSV 文件，需包含 trade_date、ts_code 和因子值列*")

    uploaded_file = st.file_uploader("上传 CSV 文件", type=["csv"], key="factor_upload")

    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            st.session_state["uploaded_df"] = df
        except Exception as e:
            st.error(f"文件读取失败: {e}")
            return

        st.markdown("#### 文件预览")
        st.dataframe(df.head(10), width="stretch")
        st.caption(f"共 {len(df)} 行，{len(df.columns)} 列")

        # 校验
        required_cols = ["trade_date", "ts_code"]
        missing = [c for c in required_cols if c not in df.columns]

        if missing:
            st.error(f"缺少必要列: {', '.join(missing)}。CSV 需包含 trade_date、ts_code 和因子值列。")
        else:
            # 唯一性检查
            dup_count = df.duplicated(subset=["trade_date", "ts_code"]).sum()
            if dup_count > 0:
                st.warning(f"⚠️ 存在 {dup_count} 条重复的 trade_date + ts_code 记录")

            # 覆盖率
            total_rows = len(df)
            valid_rows = df.dropna(subset=required_cols).shape[0]
            coverage = valid_rows / total_rows if total_rows > 0 else 0
            st.metric("数据覆盖率", f"{coverage:.1%}")

            factor_cols = [c for c in df.columns if c not in required_cols]
            if factor_cols:
                factor_col = st.selectbox("选择因子值列", factor_cols, key="upload_factor_col")
                st.markdown("**因子值列**")
                for col in factor_cols:
                    st.caption(f"`{col}` — {df[col].dtype}")

            if st.button("✅ 确认并开始验真", key="upload_confirm", type="primary", width="stretch"):
                if not factor_cols:
                    st.error("没有可用的因子值列。")
                    return
                factor_values = df[["trade_date", "ts_code", factor_col]].rename(columns={factor_col: "factor_value"})
                factor_values["trade_date"] = pd.to_datetime(factor_values["trade_date"], errors="coerce")
                factor_values["factor_value"] = pd.to_numeric(factor_values["factor_value"], errors="coerce")
                factor_id = _safe_factor_id("custom_upload", factor_col)
                spec = FactorSpec(
                    factor_id=factor_id, name=factor_id, name_cn=f"上传因子：{factor_col}",
                    description="用户上传的标准化因子值", base="uploaded",
                    inputs=[factor_col], min_window=1, source="custom",
                )
                select_factor(st.session_state, spec, factor_df=factor_values)
                st.switch_page("pages/03_传统评估.py")


def main():
    st.set_page_config(page_title="FactorGuard 因子输入", page_icon="📥", layout="wide")
    init_session()

    st.title("📥 因子输入")
    st.markdown("*选择以下任一方式引入因子*")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📦 内置因子",
        "📝 文本描述",
        "🔢 受限公式",
        "📁 因子值上传",
    ])

    with tab1:
        tab_builtin()
    with tab2:
        tab_text()
    with tab3:
        tab_formula()
    with tab4:
        tab_upload()


if __name__ == "__main__":
    main()
