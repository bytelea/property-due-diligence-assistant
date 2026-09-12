"""Synthetic, anonymized Golden Case inputs; no real documents or credentials."""

from app.models.property_fact import PropertyFact


def golden_case_facts() -> list[PropertyFact]:
    entries = [
        ("area-listing", "floor_area", 105, "m2", "listing", "EXPOSE", "Floor area: 105 m²."),
        ("area-plan", "floor_area", 92, "m2", "plan", "FLOOR_PLAN", "Floor area: 92 m²."),
        ("works", "planned_works_cost", 6500, "EUR", "minutes", "CONDOMINIUM_ASSOCIATION_MINUTES",
         "Upcoming roof works: contribution for this unit is €6,500."),
        ("extension", "extension_reference", "Rear extension exists.", None, "listing", "EXPOSE", "Rear extension exists."),
        ("planning-missing", "planning_documentation_reference", "Planning permission documentation for the rear extension was not supplied.",
         None, "pack-inventory", "OTHER", "Planning permission documentation for the rear extension was not supplied."),
    ]
    return [PropertyFact(
        fact_id=fact_id, key=key, value=value, unit=unit, document_id=document_id,
        document_type=document_type, page=1, evidence=evidence, confidence=0.95,
    ) for fact_id, key, value, unit, document_id, document_type, evidence in entries]
