"""Synthetic S01/MVP facts. Not Dresden D01-D16 and not a selected live demo."""

from datetime import date, datetime, timezone
from app.services.analysis_engine import AnalysisEngine

from app.models.property_fact import PropertyFact


def synthetic_mvp_facts() -> list[PropertyFact]:
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
        scope="unit", entity_id="synthetic-unit", document_date=date(2026, 9, 1),
        factual_date=date(2026, 10, 1) if key == "planned_works_cost" else date(2026, 9, 1),
        measurement_type="living_area" if key == "floor_area" else "unknown",
        status="approved" if key == "planned_works_cost" else "completed",
        amount_type="contribution" if key == "planned_works_cost" else None,
        frequency="one-time" if key == "planned_works_cost" else "unknown",
        project_id="synthetic-roof" if key == "planned_works_cost" else "synthetic-extension" if key in ("extension_reference", "planning_documentation_reference") else None,
        source_authority="official_plan" if document_type == "FLOOR_PLAN" else "marketing_claim" if document_type == "EXPOSE" else "documented_resolution" if document_type == "CONDOMINIUM_ASSOCIATION_MINUTES" else "document_inventory",
        evidence_role="supporting", document_applicability="applicable",
        document_presence="missing" if key == "planning_documentation_reference" else None,
        document_priority="MUST_HAVE" if key == "planning_documentation_reference" else None,
        requirement_applicable=True if key == "planning_documentation_reference" else None,
        raw_value="6,500" if key == "planned_works_cost" else None,
        number_format="en" if key == "planned_works_cost" else None,
    ) for fact_id, key, value, unit, document_id, document_type, evidence in entries]


def synthetic_engine():
    """Explicit TEST policy, not locked numerical/freshness defaults."""
    return AnalysisEngine(2.0, 0.02, as_of=date(2026, 9, 12), max_document_age_days=365,
                          analysis_timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc))
