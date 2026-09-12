from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    page: Optional[int] = Field(default=None, ge=1)


class Finding(BaseModel):
    id: str = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    type: Literal["conflict", "risk", "missing_information", "positive"]
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: List[Evidence] = Field(min_length=1)
    buyer_action: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class FinancialImpact(BaseModel):
    finding_id: str = Field(min_length=1)
    amount: float = Field(ge=0, allow_inf_nan=False)
    currency: Literal["EUR"] = "EUR"
    status: Literal["known", "estimated"]
    description: str = Field(min_length=1)


class PropertyAssessment(BaseModel):
    id: str = Field(min_length=1)
    is_demo: bool = False
    findings: List[Finding] = Field(default_factory=list)
    financial_impacts: List[FinancialImpact] = Field(default_factory=list)
