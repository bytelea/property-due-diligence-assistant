"""Pure extraction-to-canonical boundary. No rules, IO, clock or settings.

Existing routes retain legacy facts until the canonical rule migration. Call
normalize_facts after extraction and before a future canonical evaluator.
Ambiguous legacy semantics fail explicitly; the input remains unmodified.
"""
from decimal import Decimal, InvalidOperation
import re

from app.models.canonical import (
    AmountType, DocumentPresence, EvidenceRole, FactStatus, Frequency,
    MeasurementType, Payer, Scope,
)
from app.models.property_fact import CanonicalPropertyFact, PropertyFact


class NormalizationError(ValueError):
    """Messages contain field names only, never evidence or provider payloads."""


# Only enumerated spellings have compatibility mappings, not arbitrary case folding.
LEGACY_ENUM_MAPS = {
    "measurement_type": {v.value.lower(): v for v in MeasurementType},
    "scope": {**{v.value.lower(): v for v in Scope}, "WEG": Scope.OWNERS_ASSOCIATION},
    "status": {v.value.lower(): v for v in FactStatus},
    "amount_type": {v.value.lower(): v for v in AmountType},
    "frequency": {**{v.value.lower(): v for v in Frequency},
                  "one-time": Frequency.ONE_TIME, "recurring-other": Frequency.RECURRING_OTHER},
    "payer_status": {v.value.lower(): v for v in Payer},
    "evidence_role": {"supporting": EvidenceRole.SUPPORTS,
                      "contradicting": EvidenceRole.CONTRADICTS, "contextual": EvidenceRole.CONTEXT},
    "document_presence": {v.value.lower(): v for v in DocumentPresence},
}
ENUM_TYPES = dict(zip(LEGACY_ENUM_MAPS, (
    MeasurementType, Scope, FactStatus, AmountType, Frequency, Payer, EvidenceRole, DocumentPresence,
)))
UNIT_ALIASES = {"m²": "m2", "m^2": "m2", "m2": "m2"}


def normalize_fact(fact: PropertyFact) -> CanonicalPropertyFact:
    # Revalidate even model_copy/model_construct inputs before trusting their fields.
    fact = PropertyFact.model_validate(fact.model_dump(exclude_computed_fields=True))
    data = fact.model_dump(exclude_computed_fields=True)
    for field, enum in ENUM_TYPES.items():
        value = data[field]
        if value is None:
            continue
        if value in LEGACY_ENUM_MAPS[field]:
            data[field] = LEGACY_ENUM_MAPS[field][value]
        else:
            try:
                data[field] = enum(value)
            except ValueError:
                raise NormalizationError(f"Ambiguous legacy {field}; explicit canonical metadata required.") from None
    data["unit"] = UNIT_ALIASES.get(fact.unit, fact.unit)
    # A numeric string is converted only with explicitly provided currency/locale.
    # Never infer money from an allocation, share, or an arbitrary reference string.
    if isinstance(fact.value, str) and fact.currency and fact.number_format:
        token = fact.value.strip()
        if fact.raw_value is not None and fact.raw_value != fact.value:
            raise NormalizationError("Conflicting monetary value and raw_value.")
        thousands, decimal = (".", ",") if fact.number_format == "de" else (",", ".")
        grammar = r"[+-]?(?:\d+|\d{1,3}(?:" + re.escape(thousands) + r"\d{3})+)(?:" + re.escape(decimal) + r"\d+)?"
        if not re.fullmatch(grammar, token):
            raise NormalizationError("Invalid monetary format; explicit numeric value required.")
        try:
            value = Decimal(token.replace(thousands, "").replace(decimal, "."))
            data["value"] = float(value)
        except (InvalidOperation, OverflowError):
            raise NormalizationError("Invalid monetary value.") from None
        data["raw_value"] = fact.value
    return CanonicalPropertyFact.model_validate(data)


def normalize_facts(facts: list[PropertyFact]) -> list[CanonicalPropertyFact]:
    """Preserve order, identities and evidence; never merge or allocate facts."""
    return [normalize_fact(fact) for fact in facts]
