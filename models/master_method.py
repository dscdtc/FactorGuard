from pydantic import BaseModel
from typing import Literal, Optional


class Principle(BaseModel):
    id: int
    name: str
    description: str
    master_perspective: str = ""
    proxy_factors: list[str] = []
    proxy_grade: Literal["A", "B", "C", "U"] = "B"
    proxy_limitations: str = ""
    measurable: bool = True


class MasterMethodSpec(BaseModel):
    method_id: str
    name: str
    source_title: str
    source_reference: str
    source_excerpt: str
    principles: list[Principle]
    exemption_rules: list[dict] = []
    data_requirements: list[str] = []
    limitations: str = ""
    ai_berkshire_skill: Optional[str] = None