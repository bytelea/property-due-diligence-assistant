"""Three canonical MVP families only. No IO, provider calls or clock reads.

These are bounded evaluations, not complete B01/B02/B35 implementations.
Missing policy and provenance produce explicit evaluation records.
"""
from itertools import combinations
from uuid import NAMESPACE_URL, uuid5

from app.models.assessment import Evidence, Finding, FinancialImpact
from app.models.property_fact import CanonicalPropertyFact
from app.models.rule_evaluation import RuleEvaluation
from app.rules.common import AnalysisPolicy, money_is_documented

RULEBOOK_VERSION = "Rulebook.xlsx:sha256:e806f6f9a6da0aa2f286e19e84cbae1c4b98d72f25a3ae8ea5380f778590d7b6"


def provenance(f):
    missing = []
    for field in ("page", "document_date", "entity_id"):
        if getattr(f, field) is None:
            missing.append(f"{f.fact_id}.{field}")
    for field in ("scope", "source_authority"):
        if str(getattr(f, field)).upper() == "UNKNOWN":
            missing.append(f"{f.fact_id}.{field}")
    if f.document_applicability != "applicable":
        missing.append(f"{f.fact_id}.document_applicability")
    if f.evidence_role not in ("SUPPORTS", "CONTRADICTS") or not f.evidence.strip() or f.confidence <= 0:
        missing.append(f"{f.fact_id}.source_evidence")
    return missing


def freshness(f, policy):
    missing = []
    window = policy.freshness_days_by_key.get(f.key, policy.max_document_age_days)
    if policy.as_of is None:
        missing.append("policy.as_of")
    if window is None:
        missing.append(f"policy.freshness.{f.key}")
    if policy.as_of and window is not None and f.document_date:
        if not 0 <= (policy.as_of - f.document_date).days <= window:
            missing.append(f"{f.fact_id}.current_document_evidence")
    return missing


def record(rule, category, facts, state, reason, *, missing=(), result=None, inputs=None, applicable=True):
    ids = sorted(f.fact_id for f in facts)
    if state == "MISSING_INPUTS" and any(f.scope == "UNKNOWN" or not f.entity_id or f.document_applicability == "unknown" for f in facts):
        applicable = None
    return RuleEvaluation(
        evaluation_id=str(uuid5(NAMESPACE_URL, "canonical-evaluation:" + rule + ":" + ":".join(ids))),
        rule_id=rule, applicable=False if state == "NOT_APPLICABLE" else applicable,
        evaluation_status=state, rule_result=result, triggering_fact_ids=ids,
        calculation_inputs=inputs or {}, threshold_reason=reason, missing_inputs=sorted(set(missing)),
        category=category, severity="NEEDS_VERIFICATION" if state == "TRIGGERED" else None,
        source_validation_status="PROVISIONAL_POLICY" if rule == "B35" else "LOCKED_GUARDRAIL",
    )


def make_finding(evaluation, facts, *, kind, title, summary, action):
    roles = {"SUPPORTS": "supports", "CONTRADICTS": "contradicts", "CONTEXT": "context"}
    first = facts[0]
    return Finding(
        id=str(uuid5(NAMESPACE_URL, "finding:" + evaluation.evaluation_id)),
        rule_evaluation_id=evaluation.evaluation_id, rule_id=evaluation.rule_id,
        rulebook_version=RULEBOOK_VERSION, model_version="none:deterministic",
        type=kind, category={"AREA": "floor_area", "FINANCIAL": "financial", "LEGAL_TITLE": "planning"}[evaluation.category],
        canonical_category=evaluation.category, severity=evaluation.severity,
        title=title, summary=summary, buyer_action=action, status="unresolved",
        linked_facts=evaluation.triggering_fact_ids, scope="WEG" if first.scope == "OWNERS_ASSOCIATION" else first.scope.lower(),
        entity_id=first.entity_id, project_id=first.project_id,
        confidence=min(f.confidence for f in facts),
        uncertainty_reason="Verification is required; this finding does not establish buyer liability or legal compliance.",
        evaluation_status="EVALUATED", rule_result=evaluation.rule_result, threshold_reason=evaluation.threshold_reason,
        source_validation_status=evaluation.source_validation_status,
        evidence=[Evidence(source=f"{f.document_type.value}: {f.document_id}", excerpt=f.evidence,
                           page=f.page, fact_id=f.fact_id, document_id=f.document_id,
                           document_type=f.document_type.value, relation=roles[f.evidence_role],
                           source_authority=f.source_authority, extraction_confidence=f.confidence)
                  for f in facts],
    )


def floor_area(facts: list[CanonicalPropertyFact], policy: AnalysisPolicy):
    rule, category = "A19+A30", "AREA"
    candidates = [f for f in facts if f.key == "floor_area"]
    evaluations, findings = [], []
    if not candidates:
        return [record(rule, category, [], "NOT_APPLICABLE", "No supplied floor-area facts.")], []
    if len(candidates) == 1:
        return [record(rule, category, candidates, "MISSING_INPUTS", "A second comparable source is required.",
                       missing=["comparable_floor_area_source"])], []
    for left, right in combinations(candidates, 2):
        pair = [left, right]
        # Known mismatches establish non-comparability without requiring thresholds.
        mismatch = left.document_id == right.document_id or any(
            a is not None and b is not None and str(a).upper() != "UNKNOWN" and str(b).upper() != "UNKNOWN" and a != b
            for a, b in [(left.measurement_type, right.measurement_type), (left.scope, right.scope),
                         (left.entity_id, right.entity_id), (left.project_id, right.project_id)])
        if mismatch or any(f.document_applicability == "not_applicable" for f in pair):
            evaluations.append(record(rule, category, pair, "NOT_APPLICABLE", "Sources or measurement/entity/scope are not comparable."))
            continue
        missing = [m for f in pair for m in provenance(f)]
        for f in pair:
            if f.measurement_type == "UNKNOWN": missing.append(f"{f.fact_id}.measurement_type")
            if f.status == "UNKNOWN": missing.append(f"{f.fact_id}.status")
            if not (f.factual_date or f.factual_period or (f.period_start and f.period_end)):
                missing.append(f"{f.fact_id}.factual_time")
            if f.unit != "m2" or not isinstance(f.value, float) or f.value <= 0:
                missing.append(f"{f.fact_id}.normalized_area")
            if policy.as_of and f.document_date and f.document_date > policy.as_of:
                missing.append(f"{f.fact_id}.applicable_document_date")
        time = lambda f: (f.factual_date, f.factual_period, f.period_start, f.period_end, f.status)
        if time(left) != time(right): missing.append("policy.temporal_comparability")
        if policy.area_absolute_tolerance is None: missing.append("policy.area_absolute_tolerance")
        if policy.area_relative_tolerance is None: missing.append("policy.area_relative_tolerance")
        if missing:
            evaluations.append(record(rule, category, pair, "MISSING_INPUTS", "Comparable evidence and explicit materiality policy are required.", missing=missing, applicable=None if any(f.document_applicability == "unknown" for f in pair) else True))
            continue
        difference = abs(left.value - right.value)
        tolerance = max(policy.area_absolute_tolerance, policy.area_relative_tolerance * min(left.value, right.value))
        triggered = difference > tolerance
        evaluation = record(rule, category, pair, "TRIGGERED" if triggered else "EVALUATED_PASS",
                            "Absolute difference exceeds the caller-supplied tolerance." if triggered else "Difference is within the caller-supplied tolerance.",
                            inputs={"values_m2": [left.value, right.value], "difference_m2": difference,
                                    "absolute_tolerance": policy.area_absolute_tolerance,
                                    "relative_tolerance": policy.area_relative_tolerance, "effective_tolerance_m2": tolerance})
        evaluations.append(evaluation)
        if triggered:
            findings.append(make_finding(evaluation, pair, kind="conflict", title="Floor area differs across comparable documents",
                summary=f"{left.document_type.value} states {left.value:g} m²; {right.document_type.value} states {right.value:g} m² for the same measurement, entity and factual time.",
                action="Ask which floor-area figure is legally recognised and request authoritative supporting documentation."))
    return evaluations, findings


def planned_works(facts: list[CanonicalPropertyFact], policy: AnalysisPolicy):
    rule, category = "B02", "FINANCIAL"
    candidates = [f for f in facts if f.key == "planned_works_cost"]
    evaluations, findings = [], []
    if not candidates:
        return [record(rule, category, [], "NOT_APPLICABLE", "No supplied works-cost facts.")], []
    groups = {}
    for f in candidates:
        # Scope remains evidence-backed; no division of project totals.
        if f.scope in ("PROJECT", "OWNERS_ASSOCIATION", "BUILDING", "PARKING", "STORAGE"):
            evaluations.append(record(rule, category, [f], "MISSING_INPUTS", "Aggregate/other-asset cost is not a documented unit obligation.",
                                      missing=["explicit_unit_allocation", "unit_payer_and_due_date"]))
            continue
        if f.amount_type in ("ACTUAL", "BUDGET", "ESTIMATE", "RESERVE_BALANCE", "RESERVE_WITHDRAWAL") or f.frequency in ("MONTHLY", "QUARTERLY", "ANNUAL", "RECURRING_OTHER") or f.document_applicability == "not_applicable":
            evaluations.append(record(rule, category, [f], "NOT_APPLICABLE", "This bounded rule does not treat historical actual, estimates, budgets or recurring costs as one-time obligations."))
            continue
        identity = (f.entity_id, f.project_id, f.currency, f.amount_type, f.frequency, f.factual_date, f.factual_period, f.period_start, f.period_end)
        groups.setdefault(identity, []).append(f)
    for supporting in groups.values():
        first = supporting[0]
        missing = [m for f in supporting for m in provenance(f) + freshness(f, policy)]
        for f in supporting:
            if f.scope != "UNIT": missing.append(f"{f.fact_id}.unit_scope")
            if not f.project_id: missing.append(f"{f.fact_id}.project_id")
            if f.amount_type not in ("CONTRIBUTION", "SPECIAL_ASSESSMENT"): missing.append(f"{f.fact_id}.obligation_type")
            if f.frequency != "ONE_TIME": missing.append(f"{f.fact_id}.frequency")
            if f.currency != "EUR" or f.unit not in (None, "EUR") or not isinstance(f.value, float) or f.value <= 0 or not money_is_documented(f):
                missing.append(f"{f.fact_id}.documented_amount")
            if f.status in ("UNKNOWN", "PROPOSED", "CANCELLED"): missing.append(f"{f.fact_id}.obligation_status")
            if f.factual_date is None: missing.append(f"{f.fact_id}.due_date")
        if len({str(f.value) for f in supporting}) != 1:
            missing.append("consistent_unit_amount")
        # Completion is never payment. Payment evidence is matched to this obligation,
        # not merely to another amount for the same project.
        payment_states = {f.payment_status for f in supporting}
        if "paid" in payment_states and "unpaid" in payment_states:
            missing.append("reconciled_payment_status")
        if missing:
            evaluations.append(record(rule, category, supporting, "MISSING_INPUTS", "Current documented unit obligation inputs are incomplete.", missing=missing, result="NEEDS_VERIFICATION"))
            continue
        if payment_states == {"paid"}:
            evaluations.append(record(rule, category, supporting, "EVALUATED_PASS", "Matched evidence explicitly records payment; no outstanding cost is added.", result="NEEDS_VERIFICATION"))
            continue
        if "paid" in payment_states:
            evaluations.append(record(rule, category, supporting, "MISSING_INPUTS", "Payment evidence requires reconciliation.", missing=["reconciled_payment_status"], result="NEEDS_VERIFICATION"))
            continue
        historic_or_completed = first.factual_date < policy.as_of or any(f.status == "COMPLETED" for f in supporting)
        if historic_or_completed:
            if payment_states != {"unpaid"} or any(f.current_status_date is None for f in supporting):
                evaluations.append(record(rule, category, supporting, "MISSING_INPUTS", "Completion or a past due date does not establish payment or settlement.", missing=["current_outstanding_payment_evidence"], result="NEEDS_VERIFICATION"))
                continue
            if any(not 0 <= (policy.as_of - f.current_status_date).days <= policy.freshness_days_by_key.get(f.key, policy.max_document_age_days) for f in supporting):
                evaluations.append(record(rule, category, supporting, "MISSING_INPUTS", "Outstanding status requires current evidence.", missing=["current_outstanding_payment_evidence"], result="NEEDS_VERIFICATION"))
                continue
        payer = {f.payer_status for f in supporting}
        if len(payer) != 1:
            evaluations.append(record(rule, category, supporting, "MISSING_INPUTS", "Payer evidence conflicts.", missing=["reconciled_payer"], result="NEEDS_VERIFICATION"))
            continue
        evaluation = record(rule, category, supporting, "TRIGGERED", "Directly documented unit amount only; transaction liability and full B02 gate severity remain unassessed.",
                            result="NEEDS_VERIFICATION", inputs={"documented_unit_amount": first.value, "currency": first.currency,
                            "scope": first.scope, "payer_status": first.payer_status, "due_date": first.factual_date.isoformat(),
                            "buyer_liability_assumed": False})
        evaluations.append(evaluation)
        finding = make_finding(evaluation, supporting, kind="documented_fact", title="Documented unit works contribution",
                    summary=f"Evidence records a one-time EUR {first.value:,.2f} unit contribution. Payment responsibility remains {first.payer_status}; no project total is allocated or buyer liability assumed.",
                    action="Ask who is responsible for payment and request the unit assessment, current outstanding balance and payment schedule.")
        finding.financial_impact = FinancialImpact(finding_id=finding.id, amount=first.value, currency="EUR", status="known",
                description="Documented unit amount; not an assumed buyer debt.", amount_type=first.amount_type.lower(),
                scope=first.scope.lower(), entity_id=first.entity_id, project_id=first.project_id, frequency="one-time",
                payer_status=first.payer_status.lower(), factual_date=first.factual_date.isoformat(), factual_period=first.factual_period)
        findings.append(finding)
    return evaluations, findings


def planning_documents(facts: list[CanonicalPropertyFact], policy: AnalysisPolicy):
    rule, category = "B35", "LEGAL_TITLE"
    triggers = [f for f in facts if f.key in ("alteration_reference", "extension_reference")]
    references = [f for f in facts if f.key in ("planning_documentation_reference", "planning_document_presence")]
    groups = {}
    for f in triggers + references:
        groups.setdefault((f.entity_id, f.scope, f.project_id), []).append(f)
    if not groups:
        return [record(rule, category, [], "NOT_APPLICABLE", "No supplied alteration or planning/public-law evidence trigger.")], []
    evaluations, findings = [], []
    for related in groups.values():
        refs = [f for f in related if f in references]
        if refs and all(f.requirement_applicable is False or f.document_presence == "NOT_APPLICABLE" or f.document_priority == "NICE_TO_HAVE" for f in refs):
            evaluations.append(record(rule, category, related, "NOT_APPLICABLE", "Supplied inventory does not establish an applicable required document."))
            continue
        missing = [m for f in related for m in provenance(f)]
        for f in related:
            if not f.project_id: missing.append(f"{f.fact_id}.project_id")
        if not refs: missing.append("applicable_required_document_inventory")
        for f in refs:
            missing += freshness(f, policy)
            if f.requirement_applicable is not True: missing.append(f"{f.fact_id}.requirement_applicability")
            if f.document_priority not in ("MUST_HAVE", "CONDITIONAL"): missing.append(f"{f.fact_id}.document_priority")
            if f.document_presence not in ("MISSING", "SUPPLIED"): missing.append(f"{f.fact_id}.document_presence")
        states = {f.document_presence for f in refs}
        if len(states) > 1: missing.append("reconciled_document_inventory")
        if missing:
            evaluations.append(record(rule, category, related, "MISSING_INPUTS", "Planning applicability or evidence inventory is unresolved; absence is not inferred.", missing=missing, applicable=None))
            continue
        if states == {"SUPPLIED"}:
            # Presence is not evidence of the legal content of an approval.
            evaluations.append(record(rule, category, related, "MISSING_INPUTS", "Evidence is recorded as supplied, but official applicability/content has not been verified.", missing=["policy.planning_authority_validation"]))
            continue
        evaluation = record(rule, category, related, "TRIGGERED", "Applicable required-document inventory explicitly records evidence not supplied.", result="EVIDENCE_MISSING")
        evaluations.append(evaluation)
        findings.append(make_finding(evaluation, related, kind="missing_evidence", title="Applicable planning documentation not supplied",
            summary="Supporting planning/public-law evidence is not supplied according to the applicable inventory. Status remains unknown; missing evidence does not establish non-compliance.",
            action="Request the relevant approval, official plan or register extract for this alteration or public-law obligation from the seller or competent authority."))
    return evaluations, findings
