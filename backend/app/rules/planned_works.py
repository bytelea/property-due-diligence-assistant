from app.models.assessment import FinancialImpact
from app.models.property_fact import PropertyFact
from app.rules.common import AnalysisPolicy, current, make_finding, money_is_documented, time_key, traceable


def evaluate(facts: list[PropertyFact], policy: AnalysisPolicy):
    groups = {}
    for f in facts:
        if (f.canonical_key != "planned_works_cost" or not traceable(f)
            or f.scope != "unit" or not f.project_id or f.currency != "EUR" or f.unit not in (None, "EUR")
            or not isinstance(f.value, float) or f.value <= 0
            or f.amount_type != "contribution" or f.frequency != "one-time" or not money_is_documented(f)
            or f.status not in ("planned", "approved", "ordered", "ongoing")
            or f.payment_status == "paid" or not current(f, policy)
            or not f.factual_date or f.factual_date < policy.as_of):
            continue
        identity = (f.entity_id, f.project_id, f.currency, f.amount_type, f.frequency, time_key(f))
        groups.setdefault(identity, []).append(f)
    findings, impacts = [], []
    for supporting in groups.values():
        first = supporting[0]
        # A completion/cancellation/payment for the same project is not ignored.
        superseding = [f for f in facts if traceable(f) and f.entity_id == first.entity_id
                       and f.project_id == first.project_id and f.scope == first.scope
                       and f.document_date >= min(s.document_date for s in supporting)
                       and (f.status in ("completed", "cancelled") or f.payment_status == "paid")]
        if superseding or len({f.value for f in supporting}) != 1:
            continue
        finding = make_finding(
            "B01+B02", supporting, type="documented_fact", category="financial",
            severity="ATTENTION", status="open", title="Documented upcoming unit contribution",
            summary=f"The supplied evidence records a one-time EUR {first.value:,.2f} contribution for unit {first.entity_id}, project {first.project_id}. "
                    "The documented contribution is separate from any WEG/project total. Buyer/seller payment responsibility is not inferred.",
            uncertainty_reason="A documented unit contribution does not by itself establish purchaser liability; verify payment responsibility and current status.",
            buyer_action="Ask who is responsible for payment—the current owner or the purchaser—and request the unit assessment and payment schedule.",
        )
        if any(f.extraction_confidence < 1 for f in supporting):
            finding.severity = "NEEDS_VERIFICATION"
        payer = {f.payer_status for f in supporting}
        impact = FinancialImpact(
            finding_id=finding.id, amount=first.value, currency="EUR", status="known",
            amount_type="contribution", scope="unit", entity_id=first.entity_id,
            project_id=first.project_id, frequency="one-time", payer_status=next(iter(payer)) if len(payer) == 1 else "unknown",
            factual_date=first.factual_date.isoformat(), factual_period=first.factual_period,
            description="Directly evidenced unit contribution, not an allocated project estimate or assumed buyer debt.",
        )
        finding.financial_impact = impact
        findings.append(finding)
        impacts.append(impact)
    return findings, impacts
