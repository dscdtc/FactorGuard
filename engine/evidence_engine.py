"""
证据与结论引擎
"""
from datetime import datetime
from models.evidence import EvidenceRecord
from models.audit_result import AuditResult


def generate_evidence_records(eval_results, stress_results, dup_results, suitability_results):
    """生成结构化证据记录列表"""
    records = []

    # ---- 数据完整性 ----
    coverage = eval_results.get("coverage", 0.0)
    if coverage >= 0.90:
        sev = "pass"
    elif coverage >= 0.70:
        sev = "warn"
    else:
        sev = "fail"

    records.append(EvidenceRecord(
        evidence_id="E-INTEGRITY-001",
        dimension="数据完整性",
        severity=sev,
        claim=f"数据覆盖率为 {coverage:.1%}",
        evidence_ids=["coverage_rate"],
        metrics={"coverage": coverage},
        explanation=f"数据覆盖率 {coverage:.1%}"
    ))

    # ---- 时间正确性 ----
    max_delay = eval_results.get("max_delay", 0)
    if max_delay < 0:
        delay_sev = "fail"
    elif max_delay == 0:
        delay_sev = "warn"
    else:
        delay_sev = "pass"

    records.append(EvidenceRecord(
        evidence_id="E-TIMELINESS-001",
        dimension="时间正确性",
        severity=delay_sev,
        claim=f"最大时延为 {max_delay} 天",
        evidence_ids=["max_delay"],
        metrics={"max_delay": max_delay},
        explanation=f"公式中引用的最大时延为 {max_delay} 天"
    ))

    # ---- 统计支持 ----
    ic_p_value = eval_results.get("ic_p_value", 1.0)
    if ic_p_value < 0.01:
        ic_sev = "pass"
    elif ic_p_value < 0.05:
        ic_sev = "warn"
    else:
        ic_sev = "fail"

    records.append(EvidenceRecord(
        evidence_id="E-STATS-001",
        dimension="统计支持",
        severity=ic_sev,
        claim=f"IC p-value = {ic_p_value:.4f}",
        evidence_ids=["ic_p_value"],
        metrics={"ic_p_value": ic_p_value},
        explanation=f"IC 显著性检验 p-value = {ic_p_value:.4f}"
    ))

    # ---- 压力稳健性 ----
    retention_ratios = stress_results.get("retention_ratios", [])
    if retention_ratios:
        if all(r >= 0.80 for r in retention_ratios):
            stress_sev = "pass"
        elif any(r < 0.50 for r in retention_ratios):
            stress_sev = "fail"
        else:
            stress_sev = "warn"

        records.append(EvidenceRecord(
            evidence_id="E-STRESS-001",
            dimension="压力稳健性",
            severity=stress_sev,
            claim=f"压力测试留存率: {retention_ratios}",
            evidence_ids=["retention_ratios"],
            metrics={"retention_ratios": retention_ratios},
            explanation=f"各压力场景下因子留存率: {retention_ratios}"
        ))

    # ---- 信息独立性 ----
    overall_verdict = dup_results.get("overall_verdict", "不相似")
    if overall_verdict == "不相似":
        dup_sev = "pass"
    elif overall_verdict == "中等相似":
        dup_sev = "warn"
    else:
        dup_sev = "fail"

    records.append(EvidenceRecord(
        evidence_id="E-INDEPENDENCE-001",
        dimension="信息独立性",
        severity=dup_sev,
        claim=f"重复检测判词: {overall_verdict}",
        evidence_ids=["overall_verdict"],
        metrics={"overall_verdict": overall_verdict},
        explanation=f"与现有因子重复检测结果: {overall_verdict}"
    ))

    return records


def generate_audit_result(factor_id, factor_spec, eval_results, stress_results, dup_results, suitability_results):
    """生成 AuditResult 对象"""

    # 生成证据记录
    records = generate_evidence_records(eval_results, stress_results, dup_results, suitability_results)

    # 五维度评级
    dims = {}
    for r in records:
        dims[r.dimension] = r.severity

    coverage = eval_results.get("coverage", 0.0)
    max_delay = eval_results.get("max_delay", 0)
    ic_p_value = eval_results.get("ic_p_value", 1.0)
    retention_ratios = stress_results.get("retention_ratios", [])
    overall_verdict = dup_results.get("overall_verdict", "不相似")

    # 数据完整性
    if coverage >= 0.90:
        dims["数据完整性"] = "pass"
    elif coverage >= 0.70:
        dims["数据完整性"] = "warn"
    else:
        dims["数据完整性"] = "fail"

    # 时间正确性
    if max_delay < 0:
        dims["时间正确性"] = "fail"
    elif max_delay == 0:
        dims["时间正确性"] = "warn"
    else:
        dims["时间正确性"] = "pass"

    # 统计支持
    if ic_p_value < 0.01:
        dims["统计支持"] = "pass"
    elif ic_p_value < 0.05:
        dims["统计支持"] = "warn"
    else:
        dims["统计支持"] = "fail"

    # 压力稳健性
    if retention_ratios:
        if all(r >= 0.80 for r in retention_ratios):
            dims["压力稳健性"] = "pass"
        elif any(r < 0.50 for r in retention_ratios):
            dims["压力稳健性"] = "fail"
        else:
            dims["压力稳健性"] = "warn"
    else:
        dims["压力稳健性"] = "untested"

    # 信息独立性
    if overall_verdict == "不相似":
        dims["信息独立性"] = "pass"
    elif overall_verdict == "中等相似":
        dims["信息独立性"] = "warn"
    else:
        dims["信息独立性"] = "fail"

    # 总体结论
    if dims.get("时间正确性") == "fail":
        conclusion = "invalid"
    elif dims.get("数据完整性") == "fail":
        conclusion = "insufficient"
    elif dims.get("统计支持") == "pass" and dims.get("压力稳健性") == "fail":
        conclusion = "fragile"
    elif all(v == "pass" for v in dims.values()):
        conclusion = "supported"
    else:
        conclusion = "conditional"

    # 风险汇总
    risk_summary = []
    for r in records:
        if r.severity in ("fail", "warn"):
            risk_summary.append(f"[{r.dimension}] {r.claim}")

    # 下一测试推荐
    next_test = None
    if dims.get("压力稳健性") == "fail":
        next_test = "建议在不同市场环境下重新进行压力测试，验证因子在各种极端行情中的表现"
    elif dims.get("统计支持") == "warn":
        next_test = "建议延长样本期或增加样本量，提高统计显著性"
    elif dims.get("数据完整性") == "warn":
        next_test = "建议补充缺失时段数据，确保数据完整性达到90%以上"

    return AuditResult(
        factor_id=factor_id,
        run_id=f"{factor_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        timestamp=datetime.now().isoformat(),
        evidence_dimensions=dims,
        conclusion=conclusion,
        risk_summary=risk_summary,
        next_test=next_test,
        evidence_records=records
    )


def generate_evidence(results: dict, factor_id: str, factor_name: str) -> list:
    """生成证据记录列表（`09_鉴证运行.py` 使用的兼容接口）"""
    eval_results = results.get("traditional_eval", {})
    stress_results = results.get("stress_test", {})
    dup_results = results.get("duplicate_check", {})
    suit_results = results.get("suitability", {})

    records = generate_evidence_records(eval_results, stress_results, dup_results, suit_results)
    return [r.model_dump() for r in records]