from typing import List, Literal, Optional

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.canonical import (
    FindingCategory, FindingType, FindingStatus, EvidenceRole,
    EvaluationStatus, SourceValidationStatus, ReasoningConfidence,
    ResolutionOwner, ResolutionTiming, RULE_RESULTS,
)
from app.models.document import ProcessedDocument
from app.models.property_fact import CanonicalPropertyFact
from app.models.rule_evaluation import RuleEvaluation


class Evidence(BaseModel):
    source: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    page: Optional[int] = Field(default=None, ge=1)
    fact_id: Optional[str] = None
    document_id: Optional[str] = None
    document_type: Optional[str] = None
    document_name: Optional[str] = None
    relation: Literal["supports", "contradicts", "context"] | EvidenceRole = "supports"
    source_authority: str = "unknown"
    extraction_confidence: Optional[float] = Field(default=None, ge=0, le=1)

    @computed_field
    @property
    def evidence_text(self) -> str:
        return self.excerpt


class Finding(BaseModel):
    id: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "CRITICAL", "ATTENTION", "POSITIVE", "NEEDS_VERIFICATION", "INFORMATIONAL"]
    type: Literal["documented_fact", "conflict", "missing_evidence", "inference", "risk", "positive_signal", "cross_document_context"] | FindingType
    category: FindingCategory | str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: List[Evidence] = Field(min_length=1)
    buyer_action: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    confidence_label: Literal["High", "Medium", "Low"] = "Low"
    confidence_reason: str = "Legacy finding; reasoning confidence has not been separately evaluated."
    status: Literal["open", "verified", "unresolved", "informational"] | FindingStatus = "unresolved"
    linked_facts: List[str] = Field(default_factory=list)
    rule_id: str = "legacy-demo"
    rule_evaluation_id: Optional[str] = None
    canonical_category: Optional[FindingCategory] = None
    rulebook_version: str = "legacy-demo"
    model_version: str = "none"
    scope: str = "unknown"
    entity_id: Optional[str] = None
    project_id: Optional[str] = None
    uncertainty_reason: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)
    financial_impact: Optional["FinancialImpact"] = None

    # Optional until canonical rule evaluation is enabled; never invent results.
    evaluation_status: Optional[EvaluationStatus] = None
    rule_result: Optional[str] = None
    threshold_reason: Optional[str] = None
    playback_template_id: Optional[str] = None
    source_validation_status: Optional[SourceValidationStatus] = None
    reasoning_confidence: Optional[ReasoningConfidence] = None
    resolution_owner: Optional[ResolutionOwner] = None
    resolution_timing: Optional[ResolutionTiming] = None
    known_financial_impacts: List["FinancialImpact"] = Field(default_factory=list)
    possible_financial_impacts: List["FinancialImpact"] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def input_aliases(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for alias, field in (("finding_id", "id"), ("finding_type", "type"),
                             ("facts_used", "linked_facts"), ("triggering_fact_ids", "linked_facts"),
                             ("explanation", "summary")):
            if alias in value:
                if field in value and value[field] != value[alias]:
                    raise ValueError("Canonical and legacy finding fields disagree.")
                value[field] = value.pop(alias)
        return value

    @model_validator(mode="after")
    def validate_result(self):
        if self.rule_result is not None and self.rule_result not in RULE_RESULTS.get(self.rule_id, ()):
            raise ValueError("Rule result is not defined for this rule ID.")
        if any(i.status != "known" for i in self.known_financial_impacts):
            raise ValueError("Known financial impacts must be documented amounts.")
        if any(i.status != "estimated" for i in self.possible_financial_impacts):
            raise ValueError("Possible financial impacts must be labelled estimated.")
        return self

    @computed_field
    @property
    def resolution_status(self) -> str:
        return self.status.upper()

    @computed_field
    @property
    def triggering_fact_ids(self) -> List[str]:
        return self.linked_facts

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
    documents: List[ProcessedDocument] = Field(default_factory=list)
    # Technical completion is independent of decision readiness. None = not reported.
    technical_processing_completed: Optional[bool] = None
    canonical_facts: List[CanonicalPropertyFact] = Field(default_factory=list)
    rule_evaluations: List[RuleEvaluation] = Field(default_factory=list)
    rule_evaluation_completeness: Literal["not_evaluated", "complete", "incomplete"] = "not_evaluated"
    processing_status: Optional[Literal["completed", "incomplete"]] = None

    @model_validator(mode="after")
    def validate_canonical_trace(self):
        if self.rule_evaluation_completeness == "not_evaluated":
            return self
        facts = {f.fact_id: f for f in self.canonical_facts}
        evaluations = {e.evaluation_id: e for e in self.rule_evaluations}
        if len(facts) != len(self.canonical_facts) or len(evaluations) != len(self.rule_evaluations):
            raise ValueError("Canonical trace identifiers must be unique.")
        if self.rule_evaluation_completeness == "complete" and any(e.evaluation_status == "MISSING_INPUTS" for e in evaluations.values()):
            raise ValueError("Missing inputs cannot be labelled complete rule evaluation.")
        for evaluation in evaluations.values():
            if any(i not in facts for i in evaluation.triggering_fact_ids):
                raise ValueError("Evaluation references an unknown fact.")
        for finding in self.findings:
            evaluation = evaluations.get(finding.rule_evaluation_id)
            verification = evaluation is not None and evaluation.evaluation_status == "MISSING_INPUTS"
            if evaluation is None or (evaluation.evaluation_status != "TRIGGERED" and not verification) or finding.rule_id != evaluation.rule_id:
                raise ValueError("Finding requires a matching triggered evaluation.")
            if verification and (finding.severity != "NEEDS_VERIFICATION" or finding.evaluation_status != "NEEDS_INPUT"
                                 or finding.status not in ("unresolved", "UNRESOLVED") or finding.type != "missing_evidence"
                                 or finding.financial_impact is not None or finding.known_financial_impacts or finding.possible_financial_impacts):
                raise ValueError("Verification findings must preserve uncertainty without financial claims.")
            if finding.rule_result != evaluation.rule_result or (not verification and finding.severity != evaluation.severity):
                raise ValueError("Finding result and severity must match its evaluation.")
            if sorted(finding.linked_facts) != sorted(evaluation.triggering_fact_ids):
                raise ValueError("Finding and evaluation fact references disagree.")
            if sorted(e.fact_id for e in finding.evidence) != sorted(finding.linked_facts):
                raise ValueError("Finding evidence must cover every triggering fact.")
            for evidence in finding.evidence:
                fact = facts.get(evidence.fact_id)
                if fact is None or (evidence.document_id, evidence.page, evidence.excerpt) != (fact.document_id, fact.page, fact.evidence):
                    raise ValueError("Finding evidence does not match the canonical fact.")
        return self
