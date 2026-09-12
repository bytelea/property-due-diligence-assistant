"""Evaluation records, not rule execution or playback."""
from enum import StrEnum
from pydantic import Field, JsonValue, computed_field, model_validator
from app.models.canonical import FindingCategory, Severity, SourceValidationStatus, RULE_RESULTS
from app.models.property_fact import StructuredModel


class RuleEvaluationStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MISSING_INPUTS = "MISSING_INPUTS"
    EVALUATED_PASS = "EVALUATED_PASS"
    TRIGGERED = "TRIGGERED"


class RuleEvaluation(StructuredModel):
    evaluation_id: str
    rule_id: str
    applicable: bool | None
    evaluation_status: RuleEvaluationStatus
    rule_result: str | None = None
    triggering_fact_ids: list[str] = Field(default_factory=list)
    calculation_inputs: dict[str, JsonValue] = Field(default_factory=dict)
    threshold_reason: str
    missing_inputs: list[str] = Field(default_factory=list)
    category: FindingCategory
    severity: Severity | None = None
    source_validation_status: SourceValidationStatus
    playback_template_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def aliases(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            value.pop("workbook_evaluation_status", None)
            if "facts_used" in value:
                facts = value.pop("facts_used")
                if "triggering_fact_ids" in value and facts != value["triggering_fact_ids"]:
                    raise ValueError("Evaluation fact aliases disagree.")
                value["triggering_fact_ids"] = facts
        return value

    @model_validator(mode="after")
    def consistent_state(self):
        if self.rule_result is not None and self.rule_result not in RULE_RESULTS.get(self.rule_id, ()):
            raise ValueError("Undefined rule result.")
        if self.evaluation_status == "NOT_APPLICABLE" and self.applicable is not False:
            raise ValueError("Not applicable evaluation requires applicable=false.")
        if self.evaluation_status == "MISSING_INPUTS" and not self.missing_inputs:
            raise ValueError("Missing-input evaluation requires explicit missing inputs.")
        if self.evaluation_status in ("TRIGGERED", "EVALUATED_PASS"):
            if self.applicable is not True or self.missing_inputs:
                raise ValueError("Evaluated outcomes require resolved applicability and inputs.")
        if self.evaluation_status == "TRIGGERED" and (not self.triggering_fact_ids or self.severity is None):
            raise ValueError("Triggered evaluation requires facts and severity.")
        return self

    @computed_field
    @property
    def facts_used(self) -> list[str]:
        return self.triggering_fact_ids

    @computed_field
    @property
    def workbook_evaluation_status(self) -> str:
        return {"NOT_APPLICABLE": "NOT_APPLICABLE", "MISSING_INPUTS": "NEEDS_INPUT",
                "EVALUATED_PASS": "EVALUATED", "TRIGGERED": "EVALUATED"}[self.evaluation_status]
