from typing import List, Literal, Optional

from pydantic import BaseModel, Field, computed_field


class Evidence(BaseModel):
    source: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    page: Optional[int] = Field(default=None, ge=1)
    fact_id: Optional[str] = None
    document_id: Optional[str] = None
    document_type: Optional[str] = None
    relation: Literal["supports", "contradicts", "context"] = "supports"
    source_authority: str = "unknown"
    extraction_confidence: Optional[float] = Field(default=None, ge=0, le=1)

    @computed_field
    @property
    def evidence_text(self) -> str:
        return self.excerpt


class Finding(BaseModel):
    id: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "CRITICAL", "ATTENTION", "POSITIVE", "NEEDS_VERIFICATION"]
    type: Literal["documented_fact", "conflict", "missing_evidence", "inference", "risk", "positive_signal", "cross_document_context"]
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: List[Evidence] = Field(min_length=1)
    buyer_action: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    confidence_label: Literal["High", "Medium", "Low"] = "Low"
    confidence_reason: str = "Legacy finding; reasoning confidence has not been separately evaluated."
    status: Literal["open", "verified", "unresolved", "informational"] = "unresolved"
    linked_facts: List[str] = Field(default_factory=list)
    rule_id: str = "legacy-demo"
    rulebook_version: str = "legacy-demo"
    model_version: str = "none"
    scope: str = "unknown"
    entity_id: Optional[str] = None
    project_id: Optional[str] = None
    uncertainty_reason: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)
    financial_impact: Optional["FinancialImpact"] = None

    @computed_field
    @property
    def finding_id(self) -> str:
        return self.id

    @computed_field
    @property
    def finding_type(self) -> str:
        return self.type

    @computed_field
    @property
    def facts_used(self) -> List[str]:
        return self.linked_facts

    @computed_field
    @property
    def explanation(self) -> str:
        return self.summary

    @computed_field
    @property
    def financial_impact_known(self) -> Optional["FinancialImpact"]:
        return self.financial_impact if self.financial_impact and self.financial_impact.status == "known" else None

    @computed_field
    @property
    def financial_impact_possible(self) -> Optional["FinancialImpact"]:
        return self.financial_impact if self.financial_impact and self.financial_impact.status != "known" else None


class FinancialImpact(BaseModel):
    finding_id: str = Field(min_length=1)
    amount: float = Field(ge=0, allow_inf_nan=False)
    currency: Literal["EUR"] = "EUR"
    status: Literal["known", "estimated"]
    description: str = Field(min_length=1)
    amount_type: Optional[str] = None
    scope: str = "unknown"
    entity_id: Optional[str] = None
    project_id: Optional[str] = None
    frequency: str = "unknown"
    payer_status: str = "unknown"
    factual_date: Optional[str] = None
    factual_period: Optional[str] = None


class PropertyAssessment(BaseModel):
    id: str = Field(min_length=1)
    is_demo: bool = False
    findings: List[Finding] = Field(default_factory=list)
    financial_impacts: List[FinancialImpact] = Field(default_factory=list)
    summary: str = ""
    known_additional_costs: List[FinancialImpact] = Field(default_factory=list)
    potential_costs: List[FinancialImpact] = Field(default_factory=list)
    decision_readiness: Literal["READY", "READY_WITH_VERIFICATION", "NOT_DECISION_READY"] = "NOT_DECISION_READY"
    run_metadata: dict = Field(default_factory=dict)
    uncertainties: List[str] = Field(default_factory=list)
