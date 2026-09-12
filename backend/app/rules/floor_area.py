from itertools import combinations
from app.models.property_fact import PropertyFact
from app.rules.common import AnalysisPolicy, make_finding, time_key, traceable


def evaluate(facts: list[PropertyFact], policy: AnalysisPolicy):
    if policy.area_absolute_tolerance is None or policy.area_relative_tolerance is None:
        return []
    candidates = [f for f in facts if f.canonical_key == "floor_area" and f.unit == "m2"
                  and isinstance(f.value, float) and f.value > 0 and traceable(f)
                  and f.measurement_type != "unknown" and f.status != "unknown"
                  and (policy.as_of is None or f.document_date <= policy.as_of)
                  and (f.factual_date is not None or f.factual_period is not None)]
    findings = []
    for left, right in combinations(candidates, 2):
        if left.document_id == right.document_id:
            continue
        def semantics(f):
            return (f.scope, f.entity_id, f.project_id, f.measurement_type, time_key(f),
                    f.status, f.amount_type, f.currency, f.frequency)
        if semantics(left) != semantics(right):
            continue
        difference = abs(left.value - right.value)
        if difference <= max(policy.area_absolute_tolerance, policy.area_relative_tolerance * min(left.value, right.value)):
            continue
        findings.append(make_finding(
            "A19+A30", [left, right], type="conflict", category="floor_area",
            severity="NEEDS_VERIFICATION", status="unresolved",
            title="Floor area differs across comparable documents",
            summary=f"{left.document_type.value} ({left.document_id}) states {left.value:g} m²; "
                    f"{right.document_type.value} ({right.document_id}) states {right.value:g} m². "
                    f"Both refer to {left.measurement_type}, the same entity/scope and factual time/status; the difference is {difference:g} m².",
            uncertainty_reason="The applicable legally recognised area remains unverified; neither document is silently substituted for the other.",
            buyer_action="Ask which floor-area figure is legally recognised and request authoritative supporting documentation and measurements.",
            assumptions=["Materiality uses caller-supplied tolerances; numerical policy is open in workbook D14."],
        ))
    return findings
