"""Pure normalized-fact analysis; no IO, model clients, clock reads, or settings."""
import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime

from app.models.assessment import PropertyAssessment
from app.models.property_fact import PropertyFact
from app.rules import floor_area, planned_works, planning_documents
from app.rules.common import AnalysisPolicy, RULEBOOK_VERSION, current, traceable


class AnalysisEngine:
    def __init__(self, area_absolute_tolerance: float | None = None,
                 area_relative_tolerance: float | None = None, *,
                 as_of: date | None = None, max_document_age_days: int | None = None,
                 freshness_days_by_key: dict[str, int] | None = None,
                 analysis_timestamp: datetime | None = None):
        self.policy = AnalysisPolicy(area_absolute_tolerance, area_relative_tolerance, as_of, max_document_age_days,
                                     dict(freshness_days_by_key or {}))
        self.analysis_timestamp = analysis_timestamp

    def analyze(self, facts: list[PropertyFact]) -> PropertyAssessment:
        unique = {}
        for fact in facts:
            fact = PropertyFact.model_validate(fact.model_dump())
            if fact.fact_id in unique and unique[fact.fact_id] != fact:
                raise ValueError("Conflicting facts share a fact identifier.")
            unique[fact.fact_id] = fact
        normalized = sorted(unique.values(), key=lambda f: f.fact_id)
        findings = floor_area.evaluate(normalized, self.policy)
        works, impacts = planned_works.evaluate(normalized, self.policy)
        findings += works + planning_documents.evaluate(normalized, self.policy)
        metadata = {
            "model_version": "none:deterministic", "rulebook_version": RULEBOOK_VERSION,
            "engine_version": "locked-mvp-1", "analysis_timestamp": self.analysis_timestamp.isoformat() if self.analysis_timestamp else None,
            "input_document_ids": sorted({f.document_id for f in normalized}),
            "policy": {k: v.isoformat() if isinstance(v, date) else v for k, v in asdict(self.policy).items()},
        }
        fingerprint = json.dumps({"facts": [f.model_dump(mode="json") for f in normalized], "metadata": metadata}, sort_keys=True)
        uncertainties = ["Only three MVP rule families were evaluated; full document completeness and purchase readiness were not assessed."]
        if any(not traceable(f) for f in normalized):
            uncertainties.append("Some facts lack applicable source provenance or resolved scope/entity metadata and were not eligible for material findings.")
        if any(f.canonical_key == "planned_works_cost" and f.status in ("planned", "approved", "ordered", "ongoing")
               and not current(f, self.policy) for f in normalized):
            uncertainties.append("Historical or undated works evidence does not establish current status; request latest minutes, manager confirmation, and unit-specific final accounts.")
        if self.policy.area_absolute_tolerance is None or self.policy.area_relative_tolerance is None:
            uncertainties.append("Floor-area materiality requires configured tolerances (workbook decision D14).")
        if self.policy.as_of is None or (self.policy.max_document_age_days is None and not self.policy.freshness_days_by_key):
            uncertainties.append("Current financial and missing-document findings require an evaluation date and configured freshness window (D13).")
        if not self.analysis_timestamp:
            uncertainties.append("No analysis timestamp supplied; the pure engine does not invent a wall-clock audit timestamp.")
        return PropertyAssessment(
            id="assessment-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24],
            findings=sorted(findings, key=lambda f: (f.category, f.id)),
            financial_impacts=sorted(impacts, key=lambda f: f.finding_id),
            known_additional_costs=sorted(impacts, key=lambda f: f.finding_id), potential_costs=[],
            summary=f"{len(findings)} evidence-backed MVP findings; {len(impacts)} directly documented one-time unit contributions. Unresolved evidence and payer questions require verification.",
            decision_readiness="NOT_DECISION_READY", run_metadata=metadata, uncertainties=uncertainties,
        )
