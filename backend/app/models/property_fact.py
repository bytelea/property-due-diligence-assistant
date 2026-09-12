from enum import Enum
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictFloat, StrictStr, computed_field, model_validator


from app.models.canonical import (MeasurementType, Scope, FactStatus, AmountType, Frequency,
    Payer, EvidenceRole, DocumentPresence, LayoutStatus, ClaimVerificationStatus,
    PlanningEvidenceStatus, ConditionEvidenceType)


class DocumentType(str, Enum):
    EXPOSE = "EXPOSE"
    LAND_REGISTER = "LAND_REGISTER"
    DECLARATION_OF_DIVISION = "DECLARATION_OF_DIVISION"
    COMMUNITY_RULES = "COMMUNITY_RULES"
    CONDOMINIUM_ASSOCIATION_MINUTES = "CONDOMINIUM_ASSOCIATION_MINUTES"
    ECONOMIC_PLAN = "ECONOMIC_PLAN"
    ANNUAL_STATEMENT = "ANNUAL_STATEMENT"
    ENERGY_CERTIFICATE = "ENERGY_CERTIFICATE"
    RENTAL_AGREEMENT = "RENTAL_AGREEMENT"
    PROPERTY_TAX_DOCUMENT = "PROPERTY_TAX_DOCUMENT"
    FLOOR_PLAN = "FLOOR_PLAN"
    PURCHASE_DOCUMENT = "PURCHASE_DOCUMENT"
    OTHER = "OTHER"


class StructuredModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class AnonymizedDocument(StructuredModel):
    """Internal input, constructed only from the anonymization service output."""

    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=100_000, repr=False)


class DocumentClassification(StructuredModel):
    document_type: DocumentType
    confidence: float = Field(ge=0, le=1)


class FactCandidate(StructuredModel):
    key: Literal[
        "floor_area", "planned_works_cost", "alteration_reference",
        "extension_reference", "planning_documentation_reference",
    ]
    value: StrictFloat | StrictStr
    unit: Literal["m2", "EUR"] | None
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_value_and_unit(self):
        expected = {"floor_area": "m2", "planned_works_cost": "EUR"}
        if self.key in expected:
            if not isinstance(self.value, float) or self.value < 0 or self.unit != expected[self.key]:
                raise ValueError("Numeric facts require a nonnegative number and the canonical unit.")
        elif not isinstance(self.value, str) or not self.value.strip() or self.unit is not None:
            raise ValueError("Reference facts require nonempty text and no unit.")
        return self


class FactCandidates(StructuredModel):
    facts: list[FactCandidate] = Field(max_length=100)


class PropertyFact(StructuredModel):
    """Normalized facts. Legacy ingestion names remain as explicit aliases.

    Unknown metadata is retained, never guessed. Material rules require it to
    be resolved by an upstream normalization step or a reviewed fixture.
    """

    fact_id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: StrictFloat | StrictStr | bool | dict[str, JsonValue] | list[JsonValue]
    unit: str | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    document_id: str = Field(min_length=1)
    document_type: DocumentType
    page: int | None = Field(default=None, ge=1)
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    measurement_type: Literal[
        "living_area", "usable_area", "land_area", "building_usable_area",
        "tax_area", "advertised_area", "unknown",
    ] | MeasurementType = "unknown"
    scope: Literal["unit", "building", "WEG", "parking", "storage", "project", "parcel", "unknown"] | Scope = "unknown"
    entity_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    status: Literal["planned", "proposed", "approved", "ordered", "ongoing", "completed", "cancelled", "unknown"] | FactStatus = "unknown"
    amount_type: Literal[
        "estimate", "budget", "actual", "invoice", "contribution", "reserve",
        "balance", "fee", "payment", "forecast", "credit", "arrears",
    ] | AmountType | None = None
    frequency: Literal["one-time", "monthly", "annual", "recurring-other", "unknown"] | Frequency = "unknown"
    factual_date: date | None = None
    factual_period: str | None = Field(default=None, min_length=1)
    period_start: date | None = None
    period_end: date | None = None
    current_status_date: date | None = None
    document_date: date | None = None
    layout_status: LayoutStatus | None = None
    claim_verification_status: ClaimVerificationStatus | None = None
    planning_evidence_status: PlanningEvidenceStatus | None = None
    condition_evidence_type: ConditionEvidenceType | None = None
    evidence_role: Literal["supporting", "contradicting", "contextual"] | EvidenceRole = "contextual"
    # The workbook leaves precedence proposed; labels are descriptive, not ranks.
    source_authority: str = Field(default="unknown", min_length=1)
    document_applicability: Literal["applicable", "not_applicable", "unknown"] = "unknown"
    document_presence: Literal["supplied", "missing", "unclear", "not_applicable"] | DocumentPresence | None = None
    document_priority: Literal["MUST_HAVE", "CONDITIONAL", "NICE_TO_HAVE"] | None = None
    requirement_applicable: bool | None = None
    payer_status: Literal["buyer", "seller", "unit_owner", "unknown"] | Payer = "unknown"
    payment_status: Literal["unpaid", "paid", "unknown"] = "unknown"
    raw_value: str | None = None
    number_format: Literal["de", "en"] | None = None
    allocation_basis: str | None = None
    allocation_numerator: float | None = None
    allocation_denominator: float | None = Field(default=None, gt=0)

    @model_validator(mode="before")
    @classmethod
    def canonical_aliases(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for canonical, legacy in (
            ("canonical_key", "key"), ("extraction_confidence", "confidence"),
            ("source_document_id", "document_id"), ("evidence_snippet", "evidence"),
        ):
            if canonical in value:
                if legacy in value and value[legacy] != value[canonical]:
                    raise ValueError("Canonical and legacy fact fields disagree.")
                value[legacy] = value.pop(canonical)
        # Preserve EUR unit for existing clients while distinguishing currency.
        if value.get("unit") == "EUR" and not value.get("currency"):
            value["currency"] = "EUR"
        return value

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("Period start must not follow period end.")
        return self

    @computed_field
    @property
    def canonical_key(self) -> str:
        return self.key

    @computed_field
    @property
    def extraction_confidence(self) -> float:
        return self.confidence

    @computed_field
    @property
    def source_document_id(self) -> str:
        return self.document_id

    @computed_field
    @property
    def evidence_snippet(self) -> str:
        return self.evidence


class CanonicalPropertyFact(PropertyFact):
    """Explicit canonical boundary; legacy PropertyFact serialization is unchanged."""

    measurement_type: MeasurementType = MeasurementType.UNKNOWN
    scope: Scope = Scope.UNKNOWN
    status: FactStatus = FactStatus.UNKNOWN
    amount_type: AmountType | None = None
    frequency: Frequency = Frequency.UNKNOWN
    payer_status: Payer = Payer.UNKNOWN
    evidence_role: EvidenceRole = EvidenceRole.CONTEXT
    document_presence: DocumentPresence | None = None


class PropertyExtraction(StructuredModel):
    document_id: str
    classification: DocumentClassification
    facts: list[PropertyFact]
