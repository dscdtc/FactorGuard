"""
哈希工具
"""
import hashlib
import json

from config import ENGINE_VERSION


def compute_evidence_hash(
    factor_spec,
    data_snapshot_hash,
    config,
    evaluation_results,
    stress_results=None,
    duplicate_results=None,
    suitability_results=None,
    engine_version=ENGINE_VERSION,
):
    """计算证据哈希"""
    payload = json.dumps({
        "factor_spec": factor_spec.model_dump(exclude_none=True) if hasattr(factor_spec, 'model_dump') else factor_spec,
        "data_snapshot_hash": data_snapshot_hash,
        "config": config,
        "evaluation_results": evaluation_results,
        "stress_results": stress_results or {},
        "duplicate_results": duplicate_results or {},
        "suitability_results": suitability_results or {},
        "engine_version": engine_version,
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def compute_report_hash(evidence_hash, report_payload=None):
    """Hash the deterministic formal report; AI text is deliberately excluded."""
    payload = json.dumps({
        "evidence_hash": evidence_hash,
        "report_payload": report_payload or {},
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def compute_ai_analysis_hash(
    evidence_hash, analysis_payload, *, model, prompt_version
):
    """Hash optional AI analysis independently from formal evidence and report."""
    payload = json.dumps({
        "evidence_hash": evidence_hash,
        "model": model,
        "prompt_version": prompt_version,
        "analysis_payload": analysis_payload,
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
