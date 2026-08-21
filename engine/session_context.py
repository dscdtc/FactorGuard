"""Helpers for keeping Streamlit's active audit context internally consistent."""

import hashlib
import json
from typing import Any

import pandas as pd


ACTIVE_RESULT_KEYS = {
    "aligned_data",
    "aligned_context",
    "factor_df",
    "eval_results",
    "stress_results",
    "dup_results",
    "suitability_result",
    "suitability_results",
    "audit_results",
    "audit_step_status",
    "audit_run_id",
    "audit_credential",
    "alignment_error",
    "evaluation_config",
    "data_snapshot_hash",
    "automatic_data_snapshot_hash",
}


def clear_active_results(session_state: Any) -> None:
    """Invalidate results owned by the current active factor."""
    for key in ACTIVE_RESULT_KEYS:
        session_state.pop(key, None)


def select_factor(session_state: Any, spec, *, factor_df=None, is_demo: bool = False) -> None:
    """Select a factor and invalidate results owned by the previous active factor."""
    clear_active_results(session_state)

    session_state["selected_factor_id"] = spec.factor_id
    session_state["selected_factor_name"] = spec.name_cn
    session_state["selected_factor_spec"] = spec
    session_state["is_demo"] = is_demo
    session_state["audit_results"] = {}
    session_state["factor_context_hash"] = _factor_context_hash(spec, factor_df)
    if factor_df is not None:
        session_state["data_snapshot_hash"] = "uploaded:" + _dataframe_hash(factor_df)
        session_state["factor_df"] = factor_df


def set_audit_result(session_state: Any, name: str, result: dict) -> None:
    """Write one result into the active factor's audit bundle."""
    audit_results = session_state.setdefault("audit_results", {})
    audit_results[name] = result


def build_cache_context(session_state: Any, **settings) -> dict:
    """Return a deterministic cache context for the active factor and data."""
    context = {
        "factor_id": session_state.get("selected_factor_id"),
        "factor_context_hash": session_state.get("factor_context_hash"),
        "data_snapshot_hash": session_state.get("data_snapshot_hash"),
        "aligned_context": session_state.get("aligned_context"),
    }
    context.update(settings)
    return _json_safe(context)


def contextual_cache_key(prefix: str, context: dict) -> str:
    payload = json.dumps(_json_safe(context), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _factor_context_hash(spec, factor_df=None) -> str:
    spec_payload = spec.model_dump(exclude_none=True) if hasattr(spec, "model_dump") else spec
    payload = json.dumps(_json_safe(spec_payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8"))
    if isinstance(factor_df, pd.DataFrame):
        digest.update("|".encode("ascii"))
        digest.update(_dataframe_hash(factor_df).encode("ascii"))
    return digest.hexdigest()[:16]


def _dataframe_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    digest.update("|".join(map(str, frame.columns)).encode("utf-8"))
    digest.update("|".join(map(str, frame.dtypes)).encode("utf-8"))
    return digest.hexdigest()[:16]


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
