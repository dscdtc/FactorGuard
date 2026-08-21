"""
证据记录模型
"""
from pydantic import BaseModel
from typing import Literal, Optional


class EvidenceRecord(BaseModel):
    evidence_id: str
    dimension: str  # 数据完整性/时间正确性/统计支持/压力稳健性/信息独立性
    severity: Literal["pass", "warn", "fail", "untested"]
    claim: str  # 声明
    evidence_ids: list[str] = []
    metrics: dict = {}
    explanation: str = ""