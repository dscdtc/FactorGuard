"""
哈希工具
"""
import hashlib
import json


def compute_evidence_hash(factor_spec, data_snapshot_hash, config, evaluation_results):
    """计算证据哈希"""
    payload = json.dumps({
        "factor_spec": factor_spec.model_dump(exclude_none=True) if hasattr(factor_spec, 'model_dump') else factor_spec,
        "data_snapshot_hash": data_snapshot_hash,
        "config": config,
        "evaluation_results": evaluation_results
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def compute_report_hash(evidence_hash, ai_explanation):
    """计算报告哈希"""
    return hashlib.sha256(f"{evidence_hash}{ai_explanation}".encode()).hexdigest()[:16]