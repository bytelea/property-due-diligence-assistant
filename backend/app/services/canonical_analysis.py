"""Canonical-only deterministic analysis, independent of legacy rule execution."""
from dataclasses import asdict
from datetime import date
import hashlib
import json

from app.models.assessment import PropertyAssessment
from app.models.property_fact import CanonicalPropertyFact
from app.rules import canonical_mvp


def analyze_canonical(facts, policy, analysis_timestamp=None):
    unique = {}
    for fact in facts:
        if not isinstance(fact, CanonicalPropertyFact):
            raise ValueError("Canonical analysis requires normalized canonical facts.")
        fact = CanonicalPropertyFact.model_validate(fact.model_dump())
        if fact.fact_id in unique and unique[fact.fact_id] != fact:
            raise ValueError("Conflicting facts share a fact identifier.")
        unique[fact.fact_id] = fact
    facts = sorted(unique.values(), key=lambda f: f.fact_id)
    evaluations, findings = [], []
    for rule in (canonical_mvp.floor_area, canonical_mvp.planned_works, canonical_mvp.planning_documents):
        records, generated = rule(facts, policy)
        evaluations.extend(records)
        findings.extend(generated)
    from app.services.finding_projection import verification_finding
    projected = {f.rule_evaluation_id for f in findings}
    facts_by_id = {f.fact_id: f for f in facts}
    for evaluation in evaluations:
        if evaluation.evaluation_id not in projected:
            finding = verification_finding(evaluation, facts_by_id)
            if finding is not None:
                findings.append(finding)
    evaluations.sort(key=lambda e: (e.rule_id, e.evaluation_id))
    findings.sort(key=lambda f: (f.category, f.id))
    incomplete = any(e.evaluation_status == "MISSING_INPUTS" for e in evaluations)
    impacts = [f.financial_impact for f in findings if f.financial_impact is not None]
    metadata = {
        "model_version": "none:deterministic", "rulebook_version": canonical_mvp.RULEBOOK_VERSION,
        "engine_version": "canonical-mvp-3", "analysis_timestamp": analysis_timestamp.isoformat() if analysis_timestamp else None,
        "input_document_ids": sorted({f.document_id for f in facts}),
        "policy": {k: v.isoformat() if isinstance(v, date) else v for k, v in asdict(policy).items()},
        "evaluation_scope": "Three bounded MVP families only; not full B01/B02/B35 or B01-B38 coverage.",
    }
    fingerprint = json.dumps({"facts": [f.model_dump(mode="json") for f in facts], "metadata": metadata}, sort_keys=True)
    return PropertyAssessment(
        id="assessment-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24],
        findings=findings, financial_impacts=impacts, known_additional_costs=impacts,
        canonical_facts=facts, rule_evaluations=evaluations,
        rule_evaluation_completeness="incomplete" if incomplete else "complete",
        decision_readiness="NOT_DECISION_READY", run_metadata=metadata,
        summary=f"{len(findings)} evidence-backed MVP findings. Rule evaluation is {'incomplete' if incomplete else 'complete for the three supported families'}; purchase readiness has not been assessed.",
        uncertainties=["Only the three supported rule families were evaluated; no purchase-readiness conclusion was made."]
            + sorted({m for e in evaluations for m in e.missing_inputs}),
    )
