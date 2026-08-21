"""
运行记录器 - 将页面计算任务保存到 session_state.recent_runs
供 01_工作台.py 的"最近运行"列表展示
"""
from datetime import datetime


def save_run(name: str, factor_id: str, verdict: str, risk_summary: str, session_state: dict):
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