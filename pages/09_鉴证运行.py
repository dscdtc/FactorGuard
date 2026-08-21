"""
鉴证运行页面 - 一站式鉴证流程
步骤进度条：输入检查 → 数据对齐 → 传统评估 → 压力测试 → 重复检测 → 生成证据 → AI解释
"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from engine.traditional_eval import evaluate_factor
from engine.factor_computer import load_aligned_data, compute_factor_values
from engine.data_loader import get_ohlcv_data, get_basic_data
from engine.data_aligner import align_factor_returns
from engine.factor_loader import get_factor_by_id
from engine.stress_test import run_stress_tests, summarize_stress_results
from engine.evidence_engine import generate_evidence
from engine.ai_explainer import generate_summary
from engine.quality_check import run_quality_checks, summarize_quality_check
from engine.run_recorder import save_run
from ui.metric_cards import render_metric_row, render_verdict_badge
from ui.color_utils import get_verdict_color

st.set_page_config(page_title="鉴证运行", page_icon="⚙️", layout="wide")

# ============================================================
# 前提条件
# ============================================================
if "selected_factor_id" not in st.session_state or st.session_state.selected_factor_id is None:
    st.warning("⚠️ 请先在因子输入页面选择一个因子")
    st.stop()

factor_id = st.session_state.selected_factor_id
factor_name = st.session_state.get("selected_factor_name", factor_id)
forward_period = st.session_state.get("forward_period", 5)
is_demo = st.session_state.get("is_demo", False)

# Demo A 特殊处理：使用 demo_a 的篡改 spec
if is_demo and factor_id == "demo_future_leak":
    from engine.demo_data import get_demo_a_factor
    demo_a = st.session_state.get("demo_a", get_demo_a_factor())
    st.session_state["demo_a"] = demo_a
    st.session_state["selected_factor_spec"] = demo_a.get("factor_spec")
    factor_name = "Demo A: 未来函数因子"
    st.session_state["selected_factor_name"] = factor_name

st.title(f"⚙️ 鉴证运行：{factor_name}")
st.markdown(f"*因子 ID: {factor_id}*")

st.divider()

# ============================================================
# 步骤定义
# ============================================================
STEPS = [
    ("input_check", "🔍 输入检查"),
    ("data_align", "📊 数据对齐"),
    ("traditional_eval", "📈 传统评估"),
    ("stress_test", "💪 压力测试"),
    ("duplicate_check", "🔄 重复检测"),
    ("evidence_gen", "📋 生成证据"),
    ("ai_explain", "🤖 AI 解释"),
]

# 步骤状态
if "audit_step_status" not in st.session_state:
    st.session_state["audit_step_status"] = {s[0]: "pending" for s in STEPS}

if "audit_results" not in st.session_state:
    st.session_state["audit_results"] = {}

# ============================================================
# 步骤进度条
# ============================================================
def render_progress():
    status = st.session_state["audit_step_status"]
    cols = st.columns(len(STEPS))
    for i, (key, label) in enumerate(STEPS):
        with cols[i]:
            s = status.get(key, "pending")
            if s == "done":
                st.markdown(f"✅ {label}")
            elif s == "running":
                st.markdown(f"⏳ **{label}**")
            elif s == "failed":
                st.markdown(f"⚠️ {label}")
            elif s == "skipped":
                st.markdown(f"⏭️ {label}")
            else:
                st.markdown(f"⬜ {label}")

render_progress()
st.divider()

# ============================================================
# 运行按钮
# ============================================================
if st.button("🚀 开始鉴证", type="primary", width='stretch'):
    progress = st.progress(0)
    status = st.session_state["audit_step_status"]
    results = st.session_state["audit_results"]

    # 重置状态
    for k in status:
        status[k] = "pending"
    results.clear()

    total_steps = len(STEPS)

    # === Step 1: 输入检查 ===
    status["input_check"] = "running"
    progress.progress(1 / total_steps)
    st.markdown("**🔍 输入检查中...**")

    # Demo A 使用篡改后的 spec
    spec = None
    if is_demo and factor_id == "demo_future_leak":
        spec = st.session_state.get("selected_factor_spec")
    if spec is None:
        spec = get_factor_by_id(factor_id)
    if spec is None:
        status["input_check"] = "failed"
        results["input_check"] = {"status": "failed", "reason": "无法找到因子定义"}
        st.error("输入检查失败：无法找到因子定义")
        progress.empty()
    else:
        # 执行 P0 质检
        qc_results = run_quality_checks(spec, df=None, ohlcv_df=None)
        qc_summary = summarize_quality_check(qc_results)

        results["input_check"] = {
            "status": "passed" if qc_summary["all_passed"] else "warn",
            "factor_id": factor_id,
            "factor_name": spec.name_cn,
            "base": getattr(spec, 'base', 'N/A'),
            "quality_checks": qc_results,
            "quality_summary": qc_summary,
        }
        status["input_check"] = "done"

        if qc_summary["all_passed"]:
            st.success(f"✅ 输入检查通过：{spec.name_cn}（{qc_summary['passed']}/{qc_summary['total']} 项通过）")
        else:
            st.warning(f"⚠️ 输入检查完成：{spec.name_cn}（{qc_summary['passed']} 通过，{qc_summary['failed']} 未通过）")
            for r in qc_results:
                if r.get("severity") == "fail":
                    st.error(f"❌ {r['check']}: {r['detail']}")
                elif r.get("severity") == "warn":
                    st.warning(f"⚠️ {r['check']}: {r['detail']}")

    # === Step 2: 数据对齐 ===
    if status["input_check"] != "failed":
        status["data_align"] = "running"
        progress.progress(2 / total_steps)
        st.markdown("**📊 数据对齐中...**")

        aligned_data = load_aligned_data(st.session_state, forward_period)

        if aligned_data is None or aligned_data.empty:
            status["data_align"] = "failed"
            results["data_align"] = {"status": "failed", "reason": "无法加载或计算因子数据"}
            st.error("数据对齐失败：无法加载或计算因子数据")
            progress.empty()
        else:
            results["data_align"] = {
                "status": "passed",
                "rows": len(aligned_data),
                "stocks": aligned_data['ts_code'].nunique(),
                "date_range": f"{aligned_data['trade_date'].min()} ~ {aligned_data['trade_date'].max()}",
            }
            status["data_align"] = "done"
            st.success(f"✅ 数据对齐成功：{len(aligned_data):,} 行，{aligned_data['ts_code'].nunique()} 只股票")

    # === Step 3: 传统评估 ===
    if status["data_align"] == "done":
        status["traditional_eval"] = "running"
        progress.progress(3 / total_steps)
        st.markdown("**📈 传统评估中...**")

        df = aligned_data.copy()
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        eval_result = evaluate_factor(df, factor_col='factor_value', return_col='forward_return')

        results["traditional_eval"] = {
            "status": "passed",
            "ic_mean": eval_result['ic_mean'],
            "rank_ic_mean": eval_result['rank_ic_mean'],
            "icir": eval_result['icir'],
            "direction_consistency": eval_result['direction_consistency'],
            "coverage": eval_result['coverage'],
            "sample_count": eval_result['sample_count'],
        }
        status["traditional_eval"] = "done"
        st.success(f"✅ 传统评估完成：RankIC Mean = {eval_result['rank_ic_mean']:.4f}")

    # === Step 4: 压力测试 ===
    if status["traditional_eval"] == "done":
        status["stress_test"] = "running"
        progress.progress(4 / total_steps)
        st.markdown("**💪 压力测试中...**")

        try:
            stress_results = run_stress_tests(aligned_data)
            # run_stress_tests 返回 list[dict]，每项含 verdict 字段
            stress_summary = summarize_stress_results(stress_results)
            results["stress_test"] = {
                "test_results": stress_results,
                "summary": stress_summary,
            }
            status["stress_test"] = "done"
            pass_count = stress_summary.get("passed", 0)
            total_count = stress_summary.get("total", 0)
            st.success(f"✅ 压力测试完成：{pass_count}/{total_count} 项通过")
        except Exception as e:
            status["stress_test"] = "failed"
            results["stress_test"] = {"status": "failed", "reason": str(e)}
            st.warning(f"⚠️ 压力测试失败：{e}")

    # === Step 5: 重复检测 ===
    if status["stress_test"] != "failed":
        status["duplicate_check"] = "running"
        progress.progress(5 / total_steps)
        st.markdown("**🔄 重复检测中...**")

        try:
            from engine.duplicate_detect import detect_formula_similarity
            from engine.factor_loader import get_all_factors

            all_factors = get_all_factors()
            # Demo A 使用篡改后的 spec
            spec = None
            if is_demo and factor_id == "demo_future_leak":
                spec = st.session_state.get("selected_factor_spec")
            if spec is None:
                spec = get_factor_by_id(factor_id)
            duplicates = []

            if spec and all_factors:
                for other in all_factors:
                    if other.factor_id != factor_id:
                        sim = detect_formula_similarity(spec, other)
                        if sim and sim.get("similarity", 0) > 0.8:
                            duplicates.append({
                                "factor_id": other.factor_id,
                                "similarity": sim["similarity"],
                            })

            results["duplicate_check"] = {
                "status": "passed",
                "duplicates_found": len(duplicates),
                "duplicates": duplicates,
            }
            status["duplicate_check"] = "done"
            if duplicates:
                st.warning(f"⚠️ 发现 {len(duplicates)} 个疑似重复因子")
            else:
                st.success("✅ 重复检测通过：未发现重复因子")
        except Exception as e:
            status["duplicate_check"] = "failed"
            results["duplicate_check"] = {"status": "failed", "reason": str(e)}
            st.warning(f"⚠️ 重复检测失败：{e}")

    # === Step 6: 生成证据 ===
    status["evidence_gen"] = "running"
    progress.progress(6 / total_steps)
    st.markdown("**📋 生成证据中...**")

    try:
        evidence = generate_evidence(results, factor_id, factor_name)
        results["evidence"] = evidence
        status["evidence_gen"] = "done"
        st.success(f"✅ 证据生成完成：{len(evidence)} 条证据记录")
    except Exception as e:
        status["evidence_gen"] = "failed"
        results["evidence"] = []
        st.warning(f"⚠️ 证据生成失败：{e}")

    # === Step 7: AI 解释 ===
    status["ai_explain"] = "running"
    progress.progress(7 / total_steps)
    st.markdown("**🤖 AI 解释中...**")

    try:
        summary = generate_summary(results)
        results["ai_summary"] = summary
        status["ai_explain"] = "done"
        st.success("✅ AI 解释完成")
    except Exception as e:
        status["ai_explain"] = "failed"
        results["ai_summary"] = "AI 解释暂不可用"
        st.warning(f"⚠️ AI 解释失败（不影响核心流程）：{e}")

    progress.empty()
    render_progress()
    st.divider()

    # 保存运行记录到工作台
    trad = results.get("traditional_eval", {})
    rank_ic = trad.get("rank_ic_mean", 0)
    icir_val = trad.get("icir", 0)
    if rank_ic >= 0.03 and icir_val >= 0.5:
        verdict = "supported"
    elif rank_ic >= 0.01 and icir_val >= 0.3:
        verdict = "conditional"
    elif rank_ic >= 0:
        verdict = "fragile"
    else:
        verdict = "invalid"
    stress_s = results.get("stress_test", {})
    stress_summary = stress_s.get("summary", {}) if isinstance(stress_s, dict) else {}
    save_run(factor_name, factor_id, verdict,
             f"RankIC: {rank_ic:.4f}, ICIR: {icir_val:.4f}, "
             f"压力测试: {stress_summary.get('overall_verdict', 'N/A')}",
             st.session_state)

# ============================================================
# 结果展示
# ============================================================
results = st.session_state.get("audit_results", {})
if results:
    st.markdown("---")
    st.markdown("## 📋 鉴证结果摘要")

    # 传统评估指标
    trad = results.get("traditional_eval", {})
    if trad:
        st.markdown("### 📈 传统评估核心指标")
        metrics = [
            {"label": "RankIC Mean", "value": f"{trad.get('rank_ic_mean', 0):.4f}"},
            {"label": "ICIR", "value": f"{trad.get('icir', 0):.4f}"},
            {"label": "方向一致率", "value": f"{trad.get('direction_consistency', 0):.2%}"},
            {"label": "覆盖率", "value": f"{trad.get('coverage', 0):.2%}"},
        ]
        render_metric_row(metrics)

    # 压力测试
    stress = results.get("stress_test", {})
    if isinstance(stress, dict) and stress.get("test_results"):
        st.markdown("### 💪 压力测试结果")
        test_df = pd.DataFrame(stress["test_results"])
        if not test_df.empty:
            st.dataframe(test_df, width='stretch', hide_index=True)

    # 重复检测
    dup = results.get("duplicate_check", {})
    if dup.get("duplicates_found", 0) > 0:
        st.markdown("### 🔄 疑似重复因子")
        for d in dup.get("duplicates", []):
            st.warning(f"{d['factor_id']} — 相似度 {d['similarity']:.2%}")

    # AI 摘要
    ai_summary = results.get("ai_summary", "")
    if ai_summary:
        st.markdown("### 🤖 AI 分析")
        st.info(ai_summary)

    # 查看报告
    st.divider()
    if st.button("📋 查看完整报告", type="primary", width='stretch'):
        st.switch_page("pages/08_报告与凭证.py")