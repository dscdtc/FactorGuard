import streamlit as st
import pandas as pd
from models.master_method import MasterMethodSpec, Principle
from engine.master_method_loader import load_demo_master_method
from ui.metric_cards import render_verdict_badge
from ui.color_utils import COLOR_SCHEME

st.set_page_config(page_title="大师方法拆解", page_icon="🔍", layout="wide")

# ── 加载数据 ──
method = load_demo_master_method()

st.title("🔍 大师方法拆解")
st.caption(f"**{method.name}**  —  {method.source_title}")

# ── 4 个标签页 ──
t1, t2, t3, t4 = st.tabs(["📋 方法来源", "🧩 原则拆解", "🔬 代理因子送检", "⚠️ 方法论局限性"])

# ═══════════════════════════════════════════════
# Tab 1: 方法来源
# ═══════════════════════════════════════════════
with t1:
    st.subheader("📌 来源标题")
    st.markdown(f"**{method.source_title}**")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📖 原文引用")
        st.info(method.source_excerpt)
    with col_b:
        st.subheader("📂 出处链接")
        st.code(method.source_reference)

    st.subheader("🧠 对应的 ai-berkshire Skill")
    if method.ai_berkshire_skill:
        st.markdown(
            f'<span style="background:{COLOR_SCHEME["neutral"]};color:white;'
            f'padding:6px 16px;border-radius:6px;font-size:18px;font-weight:bold">'
            f'{method.ai_berkshire_skill}</span>',
            unsafe_allow_html=True
        )

    st.subheader("🎯 方法适用范围")
    st.markdown("""
    - **适用对象**：所有上市公司（银行/保险不适用第3条利息覆盖倍数）
    - **方法目标**：不错杀任何一流好公司，但能排除确定的非一流公司
    - **逻辑核心**：7条硬指标 + 3条豁免规则，宁可漏网不可误杀
    """)

# ═══════════════════════════════════════════════
# Tab 2: 原则拆解
# ═══════════════════════════════════════════════
with t2:
    st.subheader("🎭 四大视角")

    # 4 列视角卡片
    perspectives = {
        "段永平": {"angle": "商业模式与用户价值", "color": COLOR_SCHEME["pass"]},
        "巴菲特": {"angle": "财务质量与内在价值", "color": COLOR_SCHEME["neutral"]},
        "芒格": {"angle": "行业竞争与护城河", "color": COLOR_SCHEME["warn"]},
        "李录": {"angle": "风险管理与治理层评估", "color": "#7b4b94"},
    }

    cols = st.columns(4)
    for i, (master, info) in enumerate(perspectives.items()):
        with cols[i]:
            st.markdown(
                f'<div style="border:2px solid {info["color"]};border-radius:12px;'
                f'padding:16px;text-align:center;height:140px;display:flex;'
                f'flex-direction:column;justify-content:center">'
                f'<div style="font-size:20px;font-weight:bold;color:{info["color"]}">{master}</div>'
                f'<div style="font-size:14px;color:#555;margin-top:8px">{info["angle"]}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    st.markdown("---")
    st.subheader("📊 7 条原则详细列表")

    # 原则表格
    rows = []
    for p in method.principles:
        grade_color = {
            "A": COLOR_SCHEME["pass"],
            "B": COLOR_SCHEME["neutral"],
            "C": COLOR_SCHEME["warn"],
            "U": COLOR_SCHEME["untested"],
        }.get(p.proxy_grade, COLOR_SCHEME["untested"])

        rows.append({
            "编号": p.id,
            "原则名称": p.name,
            "描述": p.description,
            "大师视角": p.master_perspective,
            "可度量": "✅" if p.measurable else "❌",
            "代理评级": p.proxy_grade,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, width='stretch', hide_index=True)

    st.markdown("---")
    st.subheader("🛡️ 3 条豁免规则")

    rule_cols = st.columns(3)
    for i, rule in enumerate(method.exemption_rules):
        with rule_cols[i]:
            st.markdown(
                f'<div style="border:2px solid {COLOR_SCHEME["warn"]};border-radius:10px;'
                f'padding:14px;text-align:center">'
                f'<div style="font-size:18px;font-weight:bold;color:{COLOR_SCHEME["warn"]}">'
                f'豁免{rule["id"]}</div>'
                f'<div style="font-size:15px;font-weight:bold;margin:6px 0">{rule["name"]}</div>'
                f'<div style="font-size:13px;color:#666">{rule["description"]}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

# ═══════════════════════════════════════════════
# Tab 3: 代理因子送检
# ═══════════════════════════════════════════════
with t3:
    st.subheader("🔬 代理因子映射表")
    st.caption("B 级代理可送检因子评估流程，C/U 级代理因数据不足暂不可鉴证。")

    proxy_rows = []
    for p in method.principles:
        factors_str = "、".join(p.proxy_factors) if p.proxy_factors else "—"
        grade_color = {
            "A": COLOR_SCHEME["pass"],
            "B": COLOR_SCHEME["neutral"],
            "C": COLOR_SCHEME["warn"],
            "U": COLOR_SCHEME["untested"],
        }.get(p.proxy_grade, COLOR_SCHEME["untested"])

        if p.proxy_grade in ("B",):
            status = "🟢 可送检"
            action = "送检"
        elif p.proxy_grade in ("A",):
            status = "✅ 已验证"
            action = "查看"
        else:
            status = "🔴 不可鉴证"
            action = "—"

        proxy_rows.append({
            "原则": p.name,
            "代理因子": factors_str,
            "评级": p.proxy_grade,
            "数据状态": status,
            "操作": action,
            "局限说明": p.proxy_limitations,
        })

    proxy_df = pd.DataFrame(proxy_rows)

    # 渲染带按钮的表格
    for i, row in proxy_df.iterrows():
        cols = st.columns([1.5, 2, 0.8, 1.5, 1, 2])
        with cols[0]:
            st.markdown(f"**{row['原则']}**")
        with cols[1]:
            st.text(row["代理因子"])
        with cols[2]:
            grade = row["评级"]
            gc = {
                "A": COLOR_SCHEME["pass"],
                "B": COLOR_SCHEME["neutral"],
                "C": COLOR_SCHEME["warn"],
                "U": COLOR_SCHEME["untested"],
            }.get(grade, COLOR_SCHEME["untested"])
            st.markdown(
                f'<span style="background:{gc};color:white;padding:2px 10px;'
                f'border-radius:4px;font-weight:bold">{grade}</span>',
                unsafe_allow_html=True
            )
        with cols[3]:
            st.text(row["数据状态"])
        with cols[4]:
            if row["操作"] == "送检":
                if st.button("🔍 送检", key=f"audit_{i}", type="primary",
                          help="跳转到因子评估流程"):
                    st.session_state["selected_factor_id"] = f"master_{method.method_id}_p{row['原则']}"
                    st.switch_page("pages/03_传统评估.py")
            elif row["操作"] == "查看":
                if st.button("📋 查看", key=f"view_{i}",
                          help="查看已有验证结果"):
                    st.session_state["selected_factor_id"] = f"master_{method.method_id}_p{row['原则']}"
                    st.switch_page("pages/03_传统评估.py")
            else:
                st.text("—")
        with cols[5]:
            st.caption(row["局限说明"])

    st.markdown("---")
    st.info(
        "💡 **送检说明**：点击「送检」按钮将跳转到因子评估流程，基于本地数据对代理因子进行"
        "可行性、预测力、稳定性三维评估。C/U 级代理因子因数据缺失暂不可送检，需先补充数据源。"
    )

# ═══════════════════════════════════════════════
# Tab 4: 方法论局限性
# ═══════════════════════════════════════════════
with t4:
    st.subheader("⚠️ 局限性声明")

    st.markdown(
        f'<div style="background:{COLOR_SCHEME["warn"]};color:white;padding:16px 24px;'
        f'border-radius:10px;font-size:18px;font-weight:bold;margin-bottom:16px">'
        f'"{method.limitations}"</div>',
        unsafe_allow_html=True
    )

    st.subheader("📝 仍需进一步研究的维度")
    further_items = [
        "商业模式是否可持续",
        "管理层是否值得信赖",
        "当前估值是否合理",
        "竞争格局是否在恶化",
        "行业生命周期所处阶段",
        "宏观环境与政策风险",
    ]
    for item in further_items:
        st.markdown(f"- {item}")

    st.markdown("---")
    st.subheader("📄 引用出处")
    st.markdown(
        f"> *来源：{method.source_title}*  \n"
        f"> *路径：`{method.source_reference}`*  \n"
        f"> *{method.source_excerpt}*"
    )

    st.warning(
        "⚠️ 去劣是第一步，不是最后一步。通过筛选不等于确定好，投资决策仍需综合判断。"
    )