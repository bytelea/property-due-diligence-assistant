"""Pure locked-rulebook helpers. Inputs must already be normalized."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re
from uuid import NAMESPACE_URL, uuid5

from app.models.assessment import Evidence, Finding
from app.models.property_fact import PropertyFact

RULEBOOK_VERSION = "Rulebook.xlsx:sha256:e80b37fb043719129ba0fea709d3c800bc84bad548fea1a3b8809cda06e94abd"


@dataclass(frozen=True)
class AnalysisPolicy:
    # Workbook decisions D13-D15 are open/configurable, not locked defaults.
    area_absolute_tolerance: float | None = None
    area_relative_tolerance: float | None = None
    as_of: date | None = None
    max_document_age_days: int | None = None
    freshness_days_by_key: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        for value in (self.area_absolute_tolerance, self.area_relative_tolerance):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("Area tolerances must be finite and nonnegative.")
        if self.max_document_age_days is not None and self.max_document_age_days < 0:
            raise ValueError("Freshness window must be nonnegative.")
        if any(not isinstance(days, int) or days < 0 for days in self.freshness_days_by_key.values()):
            raise ValueError("Per-field freshness windows must be nonnegative integer days.")


def stable_id(rule: str, facts: list[PropertyFact]) -> str:
    return str(uuid5(NAMESPACE_URL, rule + ":" + ":".join(sorted(f.fact_id for f in facts))))


def traceable(f: PropertyFact) -> bool:
    return bool(f.document_id and f.page is not None and f.evidence.strip()
                and f.document_date and f.source_authority != "unknown"
                and f.extraction_confidence > 0
                and f.evidence_role in ("supporting", "contradicting")
                and f.document_applicability == "applicable"
                and f.entity_id and f.scope != "unknown")


def evidence_links(facts: list[PropertyFact]) -> list[Evidence]:
    roles = {"supporting": "supports", "contradicting": "contradicts", "contextual": "context"}
    return [Evidence(source=f"{f.document_type.value}: {f.document_id}", excerpt=f.evidence,
                     page=f.page, fact_id=f.fact_id, document_id=f.document_id,
                     document_type=f.document_type.value, relation=roles[f.evidence_role],
                     source_authority=f.source_authority, extraction_confidence=f.extraction_confidence)
            for f in sorted(facts, key=lambda f: f.fact_id)]


def time_key(f: PropertyFact):
    return (f.factual_date, f.factual_period)


def current(f: PropertyFact, policy: AnalysisPolicy) -> bool:
    max_age = policy.freshness_days_by_key.get(f.canonical_key, policy.max_document_age_days)
    return bool(policy.as_of and max_age is not None and f.document_date
                and 0 <= (policy.as_of - f.document_date).days <= max_age)


def money_is_documented(f: PropertyFact) -> bool:
    """A13: use explicit source number format and sign, never guess currency math."""
    if not f.raw_value or f.number_format is None:
        return False
    # Do not accept a substring of a different or signed amount.
    if not re.search(r"(?<![\d.,+\-])" + re.escape(f.raw_value) + r"(?!\d|[.,]\d)", f.evidence):
        return False
    token = f.raw_value.replace("\u00a0", "").replace(" ", "")
    thousands, decimal = (".", ",") if f.number_format == "de" else (",", ".")
    grammar = r"[+-]?(?:\d+|\d{1,3}(?:" + re.escape(thousands) + r"\d{3})+)(?:" + re.escape(decimal) + r"\d+)?"
    if not re.fullmatch(grammar, token):
        return False
    try:
        return Decimal(token.replace(thousands, "").replace(decimal, ".")) == Decimal(str(f.value))
    except InvalidOperation:
        return False


def make_finding(rule: str, facts: list[PropertyFact], **fields) -> Finding:
    first = facts[0]
    return Finding(
        id=stable_id(rule, facts), rule_id=rule, rulebook_version=RULEBOOK_VERSION,
        model_version="none:deterministic", linked_facts=sorted(f.fact_id for f in facts),
        evidence=evidence_links(facts), scope=first.scope, entity_id=first.entity_id,
        project_id=first.project_id, confidence=min(f.extraction_confidence for f in facts),
        confidence_label="High" if all(f.extraction_confidence == 1 for f in facts) else "Low",
        confidence_reason="Deterministic matching of explicit normalized metadata; extraction uncertainty is retained separately in every evidence link.",
        **fields,
    )
