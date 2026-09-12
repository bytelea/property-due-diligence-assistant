from app.models.assessment import FinancialImpact, Finding
from app.models.property_fact import PropertyFact
from app.rules.common import documented_number, evidence_links, matches, stable_id


def evaluate(facts: list[PropertyFact]) -> tuple[list[Finding], list[FinancialImpact]]:
    # Equal amounts are conservatively treated as one possible contribution;
    # separate event identifiers are needed before summing repeated amounts.
    groups: dict[float, list[PropertyFact]] = {}
    for fact in facts:
        if fact.key != "planned_works_cost" or fact.unit != "EUR" or fact.value <= 0:
            continue
        text = fact.evidence
        if not documented_number(fact):
            continue
        if not matches(r"planned|upcoming|future|geplant|anstehend|bevorstehend", text):
            continue
        if not matches(r"(?:this|the) (?:unit|apartment|property)'?s? (?:share|contribution)|"
                       r"(?:contribution|share|cost) (?:for|attributable to) (?:this|the) (?:unit|apartment|property)|"
                       r"anteil (?:dieser|der) wohnung|beitrag für (?:diese|die) wohnung", text):
            continue
        if matches(r"estimate|estimated|approximately|potential|\bno\b|\bnot\b|could|might|already paid|"
                   r"geschätzt|circa|ca\.|\bnicht\b|\bkein\w*\b|bereits bezahlt", text):
            continue
        groups.setdefault(fact.value, []).append(fact)
    findings, impacts = [], []
    for amount, supporting in sorted(groups.items()):
        finding_id = stable_id("planned-works", supporting)
        findings.append(Finding(
            id=finding_id, severity="high", type="risk", category="maintenance",
            title="Documented upcoming works contribution",
            summary=f"Supplied evidence documents a €{amount:,.2f} planned works contribution attributable to the unit. "
                    "Responsibility for payment needs verification.",
            evidence=evidence_links(supporting),
            buyer_action="Ask who is responsible for payment—the current owner or the purchaser—and request the payment schedule.",
            confidence=min(f.confidence for f in supporting),
        ))
        impacts.append(FinancialImpact(
            finding_id=finding_id, amount=amount, currency="EUR", status="known",
            description="Documented additional unit contribution; purchaser liability and payment status require confirmation. "
                        "Do not sum separate contributions until event identity and revisions are reconciled.",
        ))
    return findings, impacts
