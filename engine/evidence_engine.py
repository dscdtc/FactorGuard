"""
证据与结论引擎
"""
from datetime import datetime
from models.evidence import EvidenceRecord
from models.audit_result import AuditResult


def _extract_retention_ratios(stress_results: dict) -> list[float]:
    """兼容不同压力测试结果结构，提取留存率列表。"""
    ratios = stress_results.get("retention_ratios", [])
    if ratios:
        return ratios

    test_results = stress_results.get("test_results", [])
    extracted = []
    for item in test_results:
        ratio = item.get("retention_ratio")
        if ratio is not None:
            extracted.append(ratio)
    return extracted


def _result_source(result: dict) -> str:
    return result.get("source") or result.get("status") or "untested"


def _has_failed_time_check(eval_results: dict) -> bool:
    quality_checks = eval_results.get("quality_checks", [])
    return any(
        item.get("severity") == "fail"
        and item.get("evidence_id") in {"QC-WINDOW-001", "QC-TIMING-001"}
        for item in quality_checks
    )


def _normalize_duplicate_verdict(dup_results: dict) -> str:
    """兼容重复检测输出结构，归一化为整体判词。"""
    overall_verdict = dup_results.get("overall_verdict")
    if overall_verdict:
        return overall_verdict

    duplicates_found = dup_results.get("duplicates_found", 0)
    if duplicates_found <= 0:
        return "不相似"
    if duplicates_found == 1:
        return "中等相似"
    return "高度相似"


def _factor_value(factor_spec, key, default=None):
    if isinstance(factor_spec, dict):
        return factor_spec.get(key, default)
    return getattr(factor_spec, key, default)


def _direction_matches(factor_spec, rank_ic_mean) -> bool | None:
    if factor_spec is None or rank_ic_mean is None:
        return None
    expected = _factor_value(factor_spec, "expected_direction")
    if expected == "higher":
        return rank_ic_mean >= 0
    if expected == "lower":
        return rank_ic_mean <= 0
    return None


def _financial_timing_unverified(factor_spec) -> bool:
    return (
        _factor_value(factor_spec, "source") == "master_proxy"
        and _factor_value(factor_spec, "availability") == "financial_period_end_unverified"
    )


def generate_evidence_records(
    eval_results, stress_results, dup_results, suitability_results, factor_spec=None
):
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
    max_delay = eval_results.get("max_delay")
    if _has_failed_time_check(eval_results) or (max_delay is not None and max_delay < 0):
        delay_sev = "fail"
    elif _financial_timing_unverified(factor_spec):
        delay_sev = "untested"
    elif max_delay is not None and max_delay > 0:
        delay_sev = "pass"
    else:
        delay_sev = "untested"

    records.append(EvidenceRecord(
        evidence_id="E-TIMELINESS-001",
        dimension="时间正确性",
        severity=delay_sev,
        claim=(
            "财务公告时点缺失，时间正确性未完整测试"
            if _financial_timing_unverified(factor_spec)
            else (f"最大时延为 {max_delay} 天" if max_delay is not None else "时间正确性未完整测试")
        ),
        evidence_ids=["max_delay"],
        metrics={"max_delay": max_delay},
        explanation=(
            "源数据只有财务期间值，没有公告日期；代理可计算，但不能证明历史时点可得"
            if _financial_timing_unverified(factor_spec)
            else (f"公式中引用的最大时延为 {max_delay} 天" if max_delay is not None else "缺少可验证的时点检查结果")
        )
    ))

    # ---- 统计支持 ----
    ic_p_value = eval_results.get("ic_p_value")
    rank_ic_mean = eval_results.get("rank_ic_mean")
    direction_matches = _direction_matches(factor_spec, rank_ic_mean)
    if direction_matches is False:
        ic_sev = "fail"
    elif ic_p_value is None:
        ic_sev = "untested"
    elif ic_p_value < 0.01:
        ic_sev = "pass"
    elif ic_p_value < 0.05:
        ic_sev = "warn"
    else:
        ic_sev = "fail"

    records.append(EvidenceRecord(
        evidence_id="E-STATS-001",
        dimension="统计支持",
        severity=ic_sev,
        claim=(
            f"RankIC 方向与预期相反（RankIC Mean = {rank_ic_mean:.4f}）"
            if direction_matches is False
            else (f"IC p-value = {ic_p_value:.4f}" if ic_p_value is not None else "统计显著性未测试")
        ),
        evidence_ids=["ic_p_value", "rank_ic_mean", "expected_direction"],
        metrics={
            "ic_p_value": ic_p_value,
            "rank_ic_mean": rank_ic_mean,
            "expected_direction": _factor_value(factor_spec, "expected_direction"),
            "direction_matches": direction_matches,
        },
        explanation=(
            "统计显著但方向与 FactorSpec 定义相反，不能作为当前方向有效的证据"
            if direction_matches is False
            else (f"IC 显著性检验 p-value = {ic_p_value:.4f}" if ic_p_value is not None else "缺少显著性或置信区间证据")
        )
    ))

    # ---- 压力稳健性 ----
    retention_ratios = _extract_retention_ratios(stress_results)
    stress_source = _result_source(stress_results)
    stress_verdicts = [item.get("verdict") for item in stress_results.get("test_results", [])]
    if stress_source in {"demo", "untested", "failed"} or "untested" in stress_verdicts:
        stress_sev = "untested"
        records.append(EvidenceRecord(
            evidence_id="E-STRESS-001", dimension="压力稳健性", severity=stress_sev,
            claim="核心压力测试未完整执行", evidence_ids=["stress_test"],
            metrics={"source": stress_source}, explanation="演示代理或缺失测试不能作为通过证据",
        ))
    elif retention_ratios:
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
    else:
        records.append(EvidenceRecord(
            evidence_id="E-STRESS-001", dimension="压力稳健性", severity="untested",
            claim="核心压力测试未执行", evidence_ids=["stress_test"],
            metrics={"source": stress_source}, explanation="缺少可验证的压力测试结果",
        ))

    # ---- 信息独立性 ----
    dup_source = _result_source(dup_results)
    overall_verdict = _normalize_duplicate_verdict(dup_results) if dup_results else None
    if dup_source in {"untested", "failed"} or not dup_results:
        dup_sev = "untested"
    elif overall_verdict == "不相似":
        dup_sev = "pass"
    elif overall_verdict == "中等相似":
        dup_sev = "warn"
    else:
        dup_sev = "fail"

    records.append(EvidenceRecord(
        evidence_id="E-INDEPENDENCE-001",
        dimension="信息独立性",
        severity=dup_sev,
        claim=(f"重复检测判词: {overall_verdict}" if overall_verdict else "重复检测未执行"),
        evidence_ids=["overall_verdict"],
        metrics={"overall_verdict": overall_verdict},
        explanation=(f"与现有因子重复检测结果: {overall_verdict}" if overall_verdict else "缺少信息独立性证据")
    ))

    return records


def generate_audit_result(factor_id, factor_spec, eval_results, stress_results, dup_results, suitability_results):
    """生成 AuditResult 对象"""

    # 生成证据记录
    records = generate_evidence_records(
        eval_results, stress_results, dup_results, suitability_results, factor_spec
    )

    # 五维度评级
    dims = {}
    for r in records:
        dims[r.dimension] = r.severity

    coverage = eval_results.get("coverage", 0.0)
    max_delay = eval_results.get("max_delay")
    ic_p_value = eval_results.get("ic_p_value")
    rank_ic_mean = eval_results.get("rank_ic_mean")
    direction_matches = _direction_matches(factor_spec, rank_ic_mean)
    retention_ratios = _extract_retention_ratios(stress_results)
    overall_verdict = _normalize_duplicate_verdict(dup_results) if dup_results else None

    # 数据完整性
    if coverage >= 0.90:
        dims["数据完整性"] = "pass"
    elif coverage >= 0.70:
        dims["数据完整性"] = "warn"
    else:
        dims["数据完整性"] = "fail"

    # 时间正确性
    if _has_failed_time_check(eval_results) or (max_delay is not None and max_delay < 0):
        dims["时间正确性"] = "fail"
    elif _financial_timing_unverified(factor_spec):
        dims["时间正确性"] = "untested"
    elif max_delay is not None and max_delay > 0:
        dims["时间正确性"] = "pass"
    else:
        dims["时间正确性"] = "untested"

    # 统计支持
    if direction_matches is False:
        dims["统计支持"] = "fail"
    elif ic_p_value is None:
        dims["统计支持"] = "untested"
    elif ic_p_value < 0.01:
        dims["统计支持"] = "pass"
    elif ic_p_value < 0.05:
        dims["统计支持"] = "warn"
    else:
        dims["统计支持"] = "fail"

    # 压力稳健性
    stress_verdicts = [item.get("verdict") for item in stress_results.get("test_results", [])]
    if _result_source(stress_results) in {"demo", "untested", "failed"} or "untested" in stress_verdicts:
        dims["压力稳健性"] = "untested"
    elif retention_ratios:
        if all(r >= 0.80 for r in retention_ratios):
            dims["压力稳健性"] = "pass"
        elif any(r < 0.50 for r in retention_ratios):
            dims["压力稳健性"] = "fail"
        else:
            dims["压力稳健性"] = "warn"
    else:
        dims["压力稳健性"] = "untested"

    # 信息独立性
    if not dup_results or _result_source(dup_results) in {"untested", "failed"}:
        dims["信息独立性"] = "untested"
    elif overall_verdict == "不相似":
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
    elif any(v == "untested" for v in dims.values()):
        conclusion = "insufficient"
    elif dims.get("统计支持") in {"fail", "warn"}:
        conclusion = "insufficient"
    elif dims.get("统计支持") == "pass" and dims.get("压力稳健性") == "fail":
        conclusion = "fragile"
    elif all(v == "pass" for v in dims.values()) and not suitability_results:
        conclusion = "supported"
    elif all(v == "pass" for v in dims.values()):
        conclusion = "conditional"
    else:
        conclusion = "conditional"

    # 风险汇总
    risk_summary = []
    for r in records:
        if r.severity in ("fail", "warn", "untested"):
            risk_summary.append(f"[{r.dimension}] {r.claim}")

    # 下一测试推荐
    next_test = None
    if dims.get("时间正确性") == "untested":
        next_test = "建议先完成因子时点与未来函数检查"
    elif dims.get("统计支持") == "untested":
        next_test = "建议补充显著性检验或置信区间证据"
    elif dims.get("压力稳健性") == "untested":
        next_test = "建议运行完整压力测试，不能以演示摘要替代"
    elif dims.get("信息独立性") == "untested":
        next_test = "建议运行重复性检测，验证信息独立性"
    elif dims.get("压力稳健性") == "fail":
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
