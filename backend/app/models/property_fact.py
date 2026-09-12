from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictStr, model_validator


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


class PropertyFact(FactCandidate):
    fact_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_type: DocumentType
    page: int | None = Field(default=None, ge=1)


class PropertyExtraction(StructuredModel):
    document_id: str
    classification: DocumentClassification
    facts: list[PropertyFact]
