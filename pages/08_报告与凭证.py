"""
报告与凭证页面
"""
import streamlit as st
import json
import pandas as pd
from datetime import datetime

from models.evidence import EvidenceRecord
from models.audit_result import AuditResult
from engine.evidence_engine import generate_audit_result, generate_evidence_records
from engine.hash_utils import compute_evidence_hash, compute_report_hash
from engine.ai_analysis import (
    generate_ai_analysis,
    get_default_provider_id,
    get_provider_presets,
    get_provider_ui_defaults,
    is_model_api_key_configured,
)
from engine.run_recorder import save_run
from engine.factor_loader import get_precomputed_metrics, get_precomputed_source_hash
from ui.metric_cards import render_verdict_badge, render_metric_row
from ui.color_utils import get_evidence_color, get_verdict_color
from config import (
    COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL,
    DEFAULT_BOOTSTRAP_BLOCKS, DEFAULT_BOOTSTRAP_REPS, DEFAULT_BOOTSTRAP_SEED,
    ENGINE_VERSION,
)

st.set_page_config(page_title="报告与凭证", page_icon="📋", layout="wide")


def _normalize_eval_results(factor_id, audit_results, session_state):
    """统一实时评估和预计算指标字段，保证报告页可渲染。"""
    eval_results = audit_results.get("traditional_eval") or session_state.get("eval_results") or {}
    precomputed = {}
    try:
        precomputed = get_precomputed_metrics(factor_id)
    except Exception:
        precomputed = {}

    if not eval_results and not precomputed:
        return {}

    normalized = dict(eval_results)

    if precomputed:
        normalized.setdefault("ic_mean", precomputed.get("ic_mean_5d", 0.0))
        normalized.setdefault("rank_ic_mean", precomputed.get("ic_mean_5d", 0.0))
        normalized.setdefault("icir", precomputed.get("icir_5d", 0.0))
        normalized.setdefault("coverage", precomputed.get("coverage", 0.0))
        normalized.setdefault("sample_count", int(precomputed.get("usable_rows", precomputed.get("sample_rows", 0)) or 0))
        normalized.setdefault("direction_consistency", 0.0)
        normalized.setdefault("ic_p_value", None)
        no_future_check = precomputed.get("no_future_check")
        normalized.setdefault(
            "max_delay",
            1 if no_future_check is True else (-1 if no_future_check is False else None),
        )

    # 兼容旧字段名
    if "sample_count" not in normalized and "n_samples" in normalized:
        normalized["sample_count"] = normalized["n_samples"]
    if "n_samples" not in normalized and "sample_count" in normalized:
        normalized["n_samples"] = normalized["sample_count"]

    normalized.setdefault("ic_mean", 0.0)
    normalized.setdefault("rank_ic_mean", 0.0)
    normalized.setdefault("icir", 0.0)
    normalized.setdefault("direction_consistency", 0.0)
    normalized.setdefault("coverage", 0.0)
    normalized.setdefault("sample_count", 0)
    normalized.setdefault("n_samples", normalized["sample_count"])
    normalized.setdefault("ic_p_value", None)
    normalized.setdefault("max_delay", None)

    return normalized


def _normalize_stress_results(audit_results, session_state):
    """统一压力测试字段。"""
    stress_results = audit_results.get("stress_test") or session_state.get("stress_results") or {}
    if not isinstance(stress_results, dict):
        return {}

    normalized = dict(stress_results)
    test_results = normalized.get("test_results", []) or []
    retention_ratios = normalized.get("retention_ratios", [])
    if not retention_ratios and test_results:
        retention_ratios = [
            item.get("retention_ratio")
            for item in test_results
            if item.get("retention_ratio") is not None
        ]
    normalized["retention_ratios"] = retention_ratios
    normalized.setdefault("summary", {})
    return normalized


def _normalize_duplicate_results(audit_results, session_state):
    """统一重复检测字段。"""
    dup_results = audit_results.get("duplicate_check") or session_state.get("dup_results") or {}
    if not isinstance(dup_results, dict):
        return {}
    if not dup_results:
        return {}

    normalized = dict(dup_results)
    duplicates_found = normalized.get("duplicates_found")
    if duplicates_found is None:
        duplicates_found = len(normalized.get("duplicates", []))
        normalized["duplicates_found"] = duplicates_found

    if "overall_verdict" not in normalized:
        if duplicates_found <= 0:
            normalized["overall_verdict"] = "不相似"
        elif duplicates_found == 1:
            normalized["overall_verdict"] = "中等相似"
        else:
            normalized["overall_verdict"] = "高度相似"

    return normalized


def _render_ai_analysis(
    audit_results,
    factor_id,
    audit,
    records,
    evidence_hash,
):
    """Render the optional AI sidecar without touching the formal report."""
    st.caption("独立投研辅助区，不构成正式鉴证结论，也不进入正式下载内容。")

    presets = get_provider_presets()
    provider_ids = [preset.provider_id for preset in presets]
    provider_names = {preset.provider_id: preset.display_name for preset in presets}
    default_provider = get_default_provider_id()
    if default_provider not in provider_ids:
        default_provider = "custom"
    selected_provider = st.selectbox(
        "模型供应商",
        provider_ids,
        index=provider_ids.index(default_provider),
        format_func=provider_names.get,
    )
    default_model, effective_base_url = get_provider_ui_defaults(selected_provider)
    selected_model = st.text_input(
        "模型 ID",
        value=default_model,
        key=f"ai_model_{selected_provider}",
    ).strip()
    custom_base_url = None
    if selected_provider == "custom":
        custom_base_url = st.text_input(
            "自定义 Base URL",
            value=effective_base_url,
            key="ai_custom_base_url",
            placeholder="https://example.com/v1",
        ).strip()
    else:
        st.caption(f"API 根地址：`{effective_base_url}`")

    selected_config = {
        "provider": selected_provider,
        "model": selected_model,
        "base_url": custom_base_url if selected_provider == "custom" else effective_base_url,
    }

    if is_model_api_key_configured():
        st.success("API Key 环境变量已配置")
    else:
        st.warning("API Key 环境变量未配置，将使用 rule_fallback")
    st.caption("密钥仅从 FACTORGUARD_LLM_API_KEY 读取，页面不接收或保存密钥。")

    ai_analysis = audit_results.get("ai_analysis")
    if audit_results.get("ai_analysis_evidence_hash") != evidence_hash:
        ai_analysis = None
    if ai_analysis and audit_results.get("ai_analysis_config") != selected_config:
        ai_analysis = None

    if st.button(
        "生成 AI 辅助解读",
        type="secondary",
        help="仅基于当前证据生成反方质询和下一步实验建议，不修改正式结论或报告。",
    ):
        ai_result = generate_ai_analysis(
            factor_id,
            audit.conclusion,
            audit.evidence_dimensions,
            records,
            evidence_hash,
            provider=selected_provider,
            model=selected_model,
            base_url=custom_base_url,
        )
        ai_analysis = ai_result.model_dump()
        audit_results["ai_analysis"] = ai_analysis
        audit_results["ai_analysis_evidence_hash"] = evidence_hash
        audit_results["ai_analysis_config"] = selected_config
        st.session_state["audit_results"] = audit_results

    if not ai_analysis:
        st.info("尚未生成辅助解读。无模型配置时会自动生成确定性的规则降级结果。")
        return

    source_label = "模型生成" if ai_analysis.get("source") == "model" else "规则降级"
    st.info(
        f"来源：{source_label} · 供应商：{provider_names.get(ai_analysis.get('provider'), ai_analysis.get('provider', 'unknown'))} · "
        f"模型：{ai_analysis.get('model', 'unknown')} · "
        f"AI 分析哈希：`{ai_analysis.get('ai_analysis_hash', '')}`"
    )
    if ai_analysis.get("fallback_reason"):
        st.caption(f"降级原因：{ai_analysis['fallback_reason']}")
    st.markdown(f"**摘要**：{ai_analysis.get('summary', '')}")
    st.markdown("**反方质询**")
    for item in ai_analysis.get("counter_arguments", []):
        st.markdown(
            f"- {item.get('text', '')} "
            f"（证据：`{'`, `'.join(item.get('evidence_ids', []))}`）"
        )
    st.markdown("**下一步实验**")
    for item in ai_analysis.get("next_experiments", []):
        st.markdown(
            f"- {item.get('text', '')} "
            f"（证据：`{'`, `'.join(item.get('evidence_ids', []))}`）"
        )
    st.caption("以上内容仅供研究辅助，正式鉴证结论以本页确定性证据和报告为准。")


def render():
    st.title("📋 报告与凭证")

    # 从 session_state 获取数据
    audit_results = st.session_state.get("audit_results", {})
    factor_id = st.session_state.get("selected_factor_id", st.session_state.get("factor_id", "unknown"))
    factor_name = st.session_state.get("selected_factor_name", factor_id)
    factor_spec = st.session_state.get("selected_factor_spec", st.session_state.get("factor_spec", {}))

    eval_results = _normalize_eval_results(factor_id, audit_results, st.session_state)
    stress_results = _normalize_stress_results(audit_results, st.session_state)
    dup_results = _normalize_duplicate_results(audit_results, st.session_state)
    suitability_results = audit_results.get("suitability") or st.session_state.get("suitability_results", {})
    data_snapshot_hash = st.session_state.get("data_snapshot_hash") or get_precomputed_source_hash(factor_id)

    # 空状态检查
    if not eval_results:
        formal_empty, ai_empty = st.tabs(["正式报告", "AI 辅助解读"])
        with formal_empty:
            st.warning("⚠️ 暂无鉴证数据，请先运行鉴证流程。")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🚀 前往鉴证运行", type="primary", width="stretch"):
                    st.switch_page("pages/09_鉴证运行.py")
            with col_b:
                if st.button("📊 前往传统评估", type="secondary", width="stretch"):
                    st.switch_page("pages/03_传统评估.py")
        with ai_empty:
            st.info("AI 辅助解读需要引用正式 evidence_id。请先完成鉴证，再返回此 Tab。")
        return

    # 生成证据记录和鉴证结果
    records = generate_evidence_records(
        eval_results, stress_results, dup_results, suitability_results, factor_spec
    )
    audit = generate_audit_result(factor_id, factor_spec, eval_results, stress_results, dup_results, suitability_results)

    # 计算哈希
    audit_config = {
        "forward_period": st.session_state.get("forward_period", 5),
        **st.session_state.get("evaluation_config", {"time_range": "全量"}),
        "bootstrap_block_size": DEFAULT_BOOTSTRAP_BLOCKS,
        "bootstrap_reps": DEFAULT_BOOTSTRAP_REPS,
        "bootstrap_seed": DEFAULT_BOOTSTRAP_SEED,
    }
    evidence_hash = compute_evidence_hash(
        factor_spec, data_snapshot_hash, audit_config, eval_results,
        stress_results, dup_results, suitability_results,
    )
    report_payload = {
        "conclusion": audit.conclusion,
        "dimensions": audit.evidence_dimensions,
        "records": [r.model_dump() for r in records],
    }
    report_hash = compute_report_hash(evidence_hash, report_payload)

    audit.evidence_hash = evidence_hash
    audit.report_hash = report_hash
    audit.evidence_records = [r.model_dump() for r in records]

    # 结论标签映射
    conclusion_label = {
        "invalid": "无效", "insufficient": "证据不足", "fragile": "脆弱",
        "conditional": "条件有效", "supported": "当前支持"
    }.get(audit.conclusion, audit.conclusion)

    # 保存运行记录，供首页的最近运行区展示
    audit.run_id = save_run(
        factor_name,
        factor_id,
        audit.conclusion,
        audit.risk_summary[0] if audit.risk_summary else conclusion_label,
        st.session_state,
        evidence_hash=evidence_hash,
        report_hash=report_hash,
        run_params=audit_config,
    )

    st.markdown(f"**因子**: {factor_name} ({factor_id})")
    st.markdown(f"**结论**: {conclusion_label}")
    st.divider()

    tab1, tab_ai, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "总览", "AI 辅助解读", "数据与时间质检", "传统评估", "压力测试", "重复性", "适用性", "复现凭证"
    ])

    # ============ Tab 1: 总览 ============
    with tab1:
        st.subheader("总体结论")
        render_verdict_badge(audit.conclusion)

        # 最严重问题
        failures = [r for r in records if r.severity == "fail"]
        warnings = [r for r in records if r.severity == "warn"]

        st.markdown("---")
        st.subheader("最严重问题")
        if failures:
            for r in failures:
                st.error(f"**{r.dimension}**: {r.claim}")
        elif warnings:
            for r in warnings:
                st.warning(f"**{r.dimension}**: {r.claim}")
        else:
            st.success("所有维度均通过检测")

        # 证据支持 vs 证据不支持
        st.markdown("---")
        st.subheader("五维度概览")
        cols = st.columns(5)
        dim_names = ["数据完整性", "时间正确性", "统计支持", "压力稳健性", "信息独立性"]
        for i, dim in enumerate(dim_names):
            sev = audit.evidence_dimensions.get(dim, "untested")
            color = get_evidence_color(sev)
            label = {"pass": "通过", "warn": "警告", "fail": "失败", "untested": "未测"}.get(sev, sev)
            with cols[i]:
                st.markdown(
                    f'<div style="background:{color};color:white;padding:8px;'
                    f'border-radius:6px;text-align:center;font-size:14px;font-weight:bold">'
                    f'{dim}<br/>{label}</div>',
                    unsafe_allow_html=True
                )

        # 推荐下一测试
        if audit.next_test:
            st.markdown("---")
            st.subheader("推荐下一测试")
            st.info(audit.next_test)

    with tab_ai:
        _render_ai_analysis(audit_results, factor_id, audit, records, evidence_hash)

    # ============ Tab 2: 数据与时间质检 ============
    with tab2:
        st.subheader("闸门清单")

        gate_checks = []
        # 数据完整性检查项
        coverage = eval_results.get("coverage", 0.0)
        gate_checks.append({
            "检查项": "数据覆盖率",
            "结果": "pass" if coverage >= 0.90 else ("warn" if coverage >= 0.70 else "fail"),
            "详情": f"{coverage:.1%}"
        })
        # 时间正确性检查项
        max_delay = eval_results.get("max_delay")
        gate_checks.append({
            "检查项": "最大时延检查",
            "结果": "untested" if max_delay is None else ("pass" if max_delay > 0 else ("warn" if max_delay == 0 else "fail")),
            "详情": "未测试" if max_delay is None else f"{max_delay} 天"
        })
        # 样本量检查
        n_samples = eval_results.get("n_samples", 0)
        gate_checks.append({
            "检查项": "样本量",
            "结果": "pass" if n_samples >= 100 else ("warn" if n_samples >= 50 else "fail"),
            "详情": f"{n_samples} 条"
        })

        for gc in gate_checks:
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(gc["结果"], "⬜")
            st.markdown(f"{icon} **{gc['检查项']}**: {gc['详情']}")

        st.markdown("---")
        st.subheader("数据质量指标")
        cols = st.columns(3)
        with cols[0]:
            st.metric("数据覆盖率", f"{coverage:.1%}")
        with cols[1]:
            st.metric("最大时延", "未测试" if max_delay is None else f"{max_delay} 天")
        with cols[2]:
            st.metric("样本量", n_samples)

        if not audit_results.get("traditional_eval"):
            st.caption("当前报告基于预计算指标生成；如需实时重算结果，请先运行完整鉴证流程。")

    # ============ Tab 3: 传统评估 ============
    with tab3:
        st.subheader("传统评估指标")
        if eval_results:
            metrics = [
                {"label": "RankIC Mean", "value": f"{eval_results.get('rank_ic_mean', 0):.4f}"},
                {"label": "ICIR", "value": f"{eval_results.get('icir', 0):.4f}"},
                {"label": "方向一致率", "value": f"{eval_results.get('direction_consistency', 0):.2%}"},
                {"label": "覆盖率", "value": f"{eval_results.get('coverage', 0):.2%}"},
            ]
            render_metric_row(metrics)

            st.markdown("---")
            st.subheader("评估详情")
            detail_items = [
                ("IC Mean", f"{eval_results.get('ic_mean', 0):.4f}"),
                ("RankIC Mean", f"{eval_results.get('rank_ic_mean', 0):.4f}"),
                ("ICIR", f"{eval_results.get('icir', 0):.4f}"),
                ("方向一致率", f"{eval_results.get('direction_consistency', 0):.2%}"),
                ("覆盖率", f"{eval_results.get('coverage', 0):.2%}"),
                ("样本量", f"{eval_results.get('sample_count', 0):,}"),
            ]
            for label, val in detail_items:
                st.markdown(f"- **{label}**: {val}")
        else:
            st.info("暂无传统评估数据。请先运行鉴证流程。")

    # ============ Tab 4: 压力测试 ============
    with tab4:
        st.subheader("压力测试结果")
        if isinstance(stress_results, dict) and stress_results.get("test_results"):
            test_list = stress_results["test_results"]
            summary = stress_results.get("summary", {})

            # 总体结论
            overall = summary.get("overall_verdict", "untested")
            verdict_color = get_verdict_color(overall)
            verdict_label_map = {
                "pass": "通过", "warn": "警告", "fragile": "脆弱",
                "invalid": "无效", "untested": "未测试",
            }
            verdict_label = verdict_label_map.get(overall, overall)
            st.markdown(
                f'<span style="background:{verdict_color};color:white;padding:6px 16px;'
                f'border-radius:6px;font-size:18px;font-weight:bold">{verdict_label}</span>',
                unsafe_allow_html=True,
            )
            st.caption(summary.get("summary_text", ""))

            # 统计卡片
            st.markdown("---")
            stat_cols = st.columns(4)
            with stat_cols[0]:
                st.metric("测试总数", summary.get("total", 0))
            with stat_cols[1]:
                st.metric("通过", summary.get("passed", 0))
            with stat_cols[2]:
                st.metric("警告", summary.get("warned", 0))
            with stat_cols[3]:
                st.metric("未通过", summary.get("failed", 0))

            # 测试详情表
            st.markdown("---")
            st.subheader("测试详情")
            table_data = []
            for r in test_list:
                table_data.append({
                    "测试名称": r.get("test_name_cn", r.get("test_name", "")),
                    "基线 RankIC": r.get("baseline_rank_ic", 0),
                    "压力后 RankIC": r.get("stress_rank_ic", 0),
                    "保留比例": r.get("retention_ratio"),
                    "方向保持": "未测试" if r.get("direction_kept") is None else ("是" if r.get("direction_kept") else "否"),
                    "状态": r.get("verdict", ""),
                })
            if table_data:
                st.dataframe(pd.DataFrame(table_data), width="stretch", hide_index=True)
        else:
            st.info("暂无压力测试数据。请先运行鉴证流程。")

    # ============ Tab 5: 重复性 ============
    with tab5:
        st.subheader("因子重复性检测")
        if dup_results:
            dup_count = dup_results.get("duplicates_found", 0)
            if dup_count > 0:
                st.warning(f"发现 {dup_count} 个疑似重复因子")
                for d in dup_results.get("duplicates", []):
                    st.markdown(
                        f"- **{d.get('factor_id', 'N/A')}** — "
                        f"相似度 {d.get('similarity', 0):.2%}"
                    )
            else:
                st.success("未发现重复因子")
        else:
            st.info("重复检测尚未执行，信息独立性记为未测试。")

    # ============ Tab 6: 适用性 ============
    with tab6:
        st.subheader("因子适用性")
        if suitability_results:
            st.json(suitability_results)
        else:
            st.info("暂无适用性分析数据。请先在适用性地图页面运行分析。")

    # ============ Tab 7: 复现凭证 ============
    with tab7:
        st.subheader("复现凭证")

        credential = {
            "factor_id": factor_id,
            "version": "1.0.0",
            "data_snapshot": data_snapshot_hash,
            "engine_version": ENGINE_VERSION,
            "config": audit_config,
            "evidence_hash": evidence_hash,
            "report_hash": report_hash,
            "timestamp": datetime.now().isoformat(),
            "conclusion": audit.conclusion,
            "evidence_dimensions": audit.evidence_dimensions
        }

        st.json(credential)

        st.markdown("---")
        st.caption("证据哈希和报告哈希用于验证正式报告未被篡改；AI 分析使用独立哈希。")

        st.markdown("---")
        st.subheader("导出报告")

        # 生成 HTML 报告
        html_report = _generate_html_report(audit, records, evidence_hash, report_hash)
        st.download_button(
            label="导出 HTML 报告",
            data=html_report,
            file_name=f"{factor_id}_report.html",
            mime="text/html"
        )

        # 生成 Markdown 报告
        md_report = _generate_markdown_report(audit, records, evidence_hash, report_hash)
        st.download_button(
            label="导出 Markdown 报告",
            data=md_report,
            file_name=f"{factor_id}_report.md",
            mime="text/markdown"
        )

        # 导出 JSON 凭证
        json_credential = json.dumps({
            "factor_id": factor_id,
            "run_id": audit.run_id,
            "version": "1.0.0",
            "data_snapshot": data_snapshot_hash,
            "engine_version": ENGINE_VERSION,
            "config": audit_config,
            "evidence_hash": evidence_hash,
            "report_hash": report_hash,
            "conclusion": audit.conclusion,
            "evidence_dimensions": audit.evidence_dimensions,
            "risk_summary": audit.risk_summary,
            "evidence_records": [r.model_dump() for r in records]
        }, ensure_ascii=False, indent=2, default=str)

        st.download_button(
            label="导出 JSON 凭证",
            data=json_credential,
            file_name=f"{factor_id}_credential.json",
            mime="application/json"
        )


def _generate_html_report(audit, records, evidence_hash, report_hash):
    """生成 HTML 格式报告"""
    dims_html = ""
    for dim, sev in audit.evidence_dimensions.items():
        color = get_verdict_color(sev)
        label = {"pass": "通过", "warn": "警告", "fail": "失败", "untested": "未测"}.get(sev, sev)
        dims_html += f'<span style="background:{color};color:white;padding:4px 8px;border-radius:4px;margin:2px">{dim}: {label}</span> '

    records_html = ""
    for r in records:
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "untested": "⬜"}.get(r.severity, "⬜")
        records_html += f"<tr><td>{icon}</td><td>{r.dimension}</td><td>{r.claim}</td><td>{r.explanation}</td></tr>"

    conclusion_label = {
        "invalid": "无效", "insufficient": "证据不足", "fragile": "脆弱",
        "conditional": "条件有效", "supported": "当前支持"
    }.get(audit.conclusion, audit.conclusion)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>FactorGuard 报告 - {audit.factor_id}</title>
<style>
body {{ font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
h1 {{ color: #1a1a1a; }} h2 {{ color: #333; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f5f5f5; }}
</style></head>
<body>
<h1>FactorGuard 鉴证报告</h1>
<p>因子ID: {audit.factor_id} | 运行ID: {audit.run_id} | 时间: {audit.timestamp}</p>
<h2>结论: {conclusion_label}</h2>
<p>{dims_html}</p>
<h2>证据记录</h2>
<table><tr><th>状态</th><th>维度</th><th>声明</th><th>解释</th></tr>{records_html}</table>
<h2>凭证</h2>
<p>证据哈希: {evidence_hash}</p><p>报告哈希: {report_hash}</p>
</body></html>"""


def _generate_markdown_report(audit, records, evidence_hash, report_hash):
    """生成 Markdown 格式报告"""
    conclusion_label = {
        "invalid": "无效", "insufficient": "证据不足", "fragile": "脆弱",
        "conditional": "条件有效", "supported": "当前支持"
    }.get(audit.conclusion, audit.conclusion)

    lines = [
        f"# FactorGuard 鉴证报告",
        f"",
        f"| 项目 | 内容 |",
        f"|------|------|",
        f"| 因子ID | {audit.factor_id} |",
        f"| 运行ID | {audit.run_id} |",
        f"| 时间 | {audit.timestamp} |",
        f"| 结论 | {conclusion_label} |",
        f"",
        f"## 五维度评级",
        f"",
    ]

    for dim, sev in audit.evidence_dimensions.items():
        label = {"pass": "通过", "warn": "警告", "fail": "失败", "untested": "未测"}.get(sev, sev)
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "untested": "⬜"}.get(sev, "⬜")
        lines.append(f"- {icon} {dim}: {label}")

    lines.append("")
    lines.append("## 证据记录")
    lines.append("")
    lines.append("| 状态 | 维度 | 声明 | 解释 |")
    lines.append("|------|------|------|------|")

    for r in records:
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "untested": "⬜"}.get(r.severity, "⬜")
        lines.append(f"| {icon} | {r.dimension} | {r.claim} | {r.explanation} |")

    lines.append("")
    lines.append("## 凭证")
    lines.append(f"- 证据哈希: `{evidence_hash}`")
    lines.append(f"- 报告哈希: `{report_hash}`")

    return "\n".join(lines)


render()
