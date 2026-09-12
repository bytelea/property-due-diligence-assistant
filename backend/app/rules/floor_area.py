from itertools import combinations

from app.models.assessment import Finding
from app.models.property_fact import DocumentType, PropertyFact
from app.rules.common import documented_number, evidence_links, matches, stable_id


def area_basis(fact: PropertyFact) -> str | None:
    for basis, pattern in (
        ("living", r"living area|wohnfläche"),
        ("usable", r"usable area|nutzfläche"),
        ("internal", r"internal area|innenfläche"),
    ):
        if matches(pattern, fact.evidence):
            return basis
    return None


def evaluate(facts: list[PropertyFact], absolute_tolerance: float, relative_tolerance: float) -> list[Finding]:
    candidates = [f for f in facts if f.key == "floor_area" and f.unit == "m2"
                  and f.value > 0 and f.document_type in (DocumentType.EXPOSE, DocumentType.FLOOR_PLAN)
                  and documented_number(f)]
    findings = []
    for left, right in combinations(candidates, 2):
        if left.document_id == right.document_id or left.document_type == right.document_type:
            continue
        if area_basis(left) and area_basis(right) and area_basis(left) != area_basis(right):
            continue
        difference = abs(left.value - right.value)
        threshold = max(absolute_tolerance, relative_tolerance * min(left.value, right.value))
        if difference <= threshold:
            continue
        pair = [left, right]
        findings.append(Finding(
            id=stable_id("floor-area-conflict", pair), severity="high", type="conflict",
            category="floor_area", title="Floor area differs across documents",
            summary=f"{left.document_type.value} ({left.document_id}) states {left.value:g} m²; "
                    f"{right.document_type.value} ({right.document_id}) states {right.value:g} m². "
                    f"The difference is {difference:g} m²; the applicable measurement basis needs verification.",
            evidence=evidence_links(pair),
            buyer_action="Ask which floor-area figure is legally recognised and request supporting documentation and measurements.",
            confidence=min(f.confidence for f in pair),
        ))
    return findings
