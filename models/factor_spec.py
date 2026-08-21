from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date


class FactorSpec(BaseModel):
    factor_id: str
    name: str
    name_cn: str
    version: str = "1.0.0"
    description: str = ""
    formula: Optional[str] = None
    formula_cn: Optional[str] = None
    expected_direction: Literal["higher", "lower"] = "higher"
    category: str = ""
    base: str = ""
    transform: str = ""
    params: dict = {}
    inputs: list[str] = []
    frequency: Literal["1d"] = "1d"
    availability: str = "after_close"
    availability_lag: int = 1
    min_window: int = 20
    universe_rule: str = "historical_all_a"
    preprocess: str = "mad3_zscore"
    neutralization: Optional[str] = None
    source: str = "builtin"
    source_reference: Optional[str] = None
    rationale_cn: Optional[str] = None