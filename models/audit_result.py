"""
鉴证结果模型
"""
from pydantic import BaseModel
from typing import Literal, Optional


class AuditResult(BaseModel):
    factor_id: str
    run_id: str
    timestamp: str
    data_snapshot: str = ""
    evidence_hash: str = ""
    report_hash: str = ""
    conclusion: Literal["invalid", "insufficient", "fragile", "conditional", "supported"]
    evidence_dimensions: dict = {}  # 五维度评级
    risk_summary: list[str] = []
    next_test: Optional[str] = None
    evidence_records: list = []