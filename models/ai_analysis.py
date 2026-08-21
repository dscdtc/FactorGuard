"""Structured contract for optional AI-assisted audit analysis."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


Conclusion = Literal["invalid", "insufficient", "fragile", "conditional", "supported"]


class AIAnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class AIModelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conclusion: Conclusion
    summary: str = Field(min_length=1, max_length=1000)
    counter_arguments: list[AIAnalysisItem] = Field(min_length=1, max_length=3)
    next_experiments: list[AIAnalysisItem] = Field(min_length=1, max_length=3)


class AIAnalysisResult(AIModelPayload):
    model_config = ConfigDict(extra="forbid")

    source: Literal["model", "rule_fallback"]
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)
    ai_analysis_hash: str = ""
    fallback_reason: Optional[str] = None
    disclaimer: str = "AI 辅助解读，不构成正式鉴证结论。"
