"""
运行记录器 - 将页面计算任务保存到 session_state.recent_runs
供 01_工作台.py 的"最近运行"列表展示
"""
from datetime import datetime
import json
import uuid

from engine.factor_loader import _get_conn


def save_run(
    name: str,
    factor_id: str,
    verdict: str,
    risk_summary: str,
    session_state: dict,
    *,
    evidence_hash: str | None = None,
    report_hash: str | None = None,
    run_params: dict | None = None,
) -> str:
    """保存一次运行记录到 session_state

    Parameters
    ----------
    name : str
        因子显示名称
    factor_id : str
        因子唯一标识
    verdict : str
        裁决结果，如 "supported", "conditional", "fragile", "invalid"
    risk_summary : str
        简短的风险摘要
    session_state : dict
        Streamlit session_state 字典
    """
    if "recent_runs" not in session_state:
        session_state["recent_runs"] = []

    runs = session_state["recent_runs"]
    # 移除同一因子的旧记录，避免重复
    runs = [r for r in runs if r.get("factor_id") != factor_id]
    runs.insert(0, {
        "name": name,
        "factor_id": factor_id,
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "verdict": verdict,
        "risk_summary": risk_summary,
    })
    # 最多保留 20 条
    session_state["recent_runs"] = runs[:20]

    run_id = session_state.get("audit_run_id") or f"run-{uuid.uuid4().hex[:16]}"
    session_state["audit_run_id"] = run_id

    conn = None
    try:
        from engine.factor_loader import _insert_factor_metadata, init_db
        from models.factor_spec import FactorSpec

        init_db()
        conn = _get_conn()
        now = datetime.now().isoformat()

        # Custom/uploaded factors must exist before the audit_runs foreign key is written.
        spec = session_state.get("selected_factor_spec")
        if isinstance(spec, FactorSpec) and spec.factor_id == factor_id:
            _insert_factor_metadata(conn, spec, now)
        else:
            metadata_exists = conn.execute(
                "SELECT 1 FROM factor_metadata WHERE factor_id = ?", [factor_id]
            ).fetchone()
            if metadata_exists is None:
                placeholder = FactorSpec(
                    factor_id=factor_id,
                    name=factor_id,
                    name_cn=name,
                    category="未分类",
                    source="session",
                )
                _insert_factor_metadata(conn, placeholder, now)

        params = {"name": name, "risk_summary": risk_summary}
        params.update(run_params or {})
        conn.execute(
            """
            INSERT OR REPLACE INTO audit_runs
                (run_id, factor_id, status, conclusion, evidence_hash, report_hash,
                 run_params, started_at, completed_at, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?,
                COALESCE((SELECT started_at FROM audit_runs WHERE run_id = ?), ?), ?, NULL)
            """,
            [
                run_id, factor_id, "completed", verdict,
                evidence_hash, report_hash,
                json.dumps(params, ensure_ascii=False, default=str),
                run_id, now, now,
            ],
        )
        session_state.pop("run_persistence_error", None)
    except Exception as exc:
        # Session history remains available if the local metadata database is locked.
        session_state["run_persistence_error"] = str(exc)
    finally:
        if conn is not None:
            conn.close()

    return run_id
