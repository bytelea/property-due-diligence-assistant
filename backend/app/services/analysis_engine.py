"""Deterministic analysis of facts belonging to ONE property; no external calls."""

import hashlib
import json
import math

from app.models.assessment import PropertyAssessment
from app.models.property_fact import PropertyFact
from app.rules import floor_area, planned_works, planning_documents


class AnalysisEngine:
    def __init__(self, area_absolute_tolerance: float = 2.0, area_relative_tolerance: float = 0.02):
        if any(not math.isfinite(v) or v < 0 for v in (area_absolute_tolerance, area_relative_tolerance)):
            raise ValueError("Area tolerances must be finite and nonnegative.")
        self.absolute_tolerance = area_absolute_tolerance
        self.relative_tolerance = area_relative_tolerance

    def analyze(self, facts: list[PropertyFact]) -> PropertyAssessment:
        unique = {}
        for fact in facts:
            # Revalidate to reject objects constructed without Pydantic validation.
            fact = PropertyFact.model_validate(fact.model_dump())
            if fact.fact_id in unique and unique[fact.fact_id] != fact:
                raise ValueError("Conflicting facts share a fact identifier.")
            unique[fact.fact_id] = fact
        normalized = sorted(unique.values(), key=lambda f: f.fact_id)
        findings = floor_area.evaluate(normalized, self.absolute_tolerance, self.relative_tolerance)
        works, impacts = planned_works.evaluate(normalized)
        findings += works + planning_documents.evaluate(normalized)
        fingerprint = json.dumps({
            "version": "mvp-1", "facts": [f.model_dump(mode="json") for f in normalized],
            "area_tolerances": [self.absolute_tolerance, self.relative_tolerance],
        }, sort_keys=True, ensure_ascii=False)
        return PropertyAssessment(
            id="assessment-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24],
            findings=sorted(findings, key=lambda f: (f.category, f.id)),
            financial_impacts=sorted(impacts, key=lambda f: f.finding_id),
        )
