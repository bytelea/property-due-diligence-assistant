"""Synthetic fixtures for demonstrating the assessment API; no external calls."""

from app.models.assessment import Evidence, FinancialImpact, Finding, PropertyAssessment


def build_demo_assessment() -> PropertyAssessment:
    return PropertyAssessment(
        id="demo-property-assessment",
        is_demo=True,
        findings=[
            Finding(
                id="floor-area-conflict",
                severity="high",
                type="conflict",
                category="floor_area",
                title="Floor area conflict",
                summary="The listing states 105 m², but the floor plan states 92 m²: a difference of 13 m².",
                evidence=[
                    Evidence(source="Demo estate agent listing", excerpt="Floor area: 105 m²"),
                    Evidence(source="Demo floor plan", excerpt="Total internal area: 92 m²"),
                ],
                buyer_action="Ask the agent which floor-area figure is legally recognised and request supporting measurements and documentation.",
                confidence=1.0,
            ),
            Finding(
                id="upcoming-works",
                severity="high",
                type="risk",
                category="maintenance",
                title="Upcoming works contribution",
                summary="Management documents identify a known €6,500 works contribution. Responsibility for payment has not been confirmed.",
                evidence=[
                    Evidence(source="Demo management minutes", excerpt="Upcoming works contribution for this property: €6,500."),
                ],
                buyer_action="Confirm whether the €6,500 contribution will be paid by the current owner or purchaser, and request the payment schedule.",
                confidence=1.0,
            ),
            Finding(
                id="missing-planning-documentation",
                severity="medium",
                type="missing_information",
                category="planning",
                title="Missing planning documentation",
                summary="An alteration is referenced, but supporting planning documents are absent from the supplied demo pack. Compliance remains unverified.",
                evidence=[
                    Evidence(source="Demo estate agent listing", excerpt="The property includes a rear extension."),
                    Evidence(source="Demo document inventory", excerpt="Supplied: listing, floor plan, management minutes. No planning permission or compliance documents supplied."),
                ],
                buyer_action="Request planning permission and relevant compliance documentation for the extension before proceeding.",
                confidence=1.0,
            ),
        ],
        financial_impacts=[
            FinancialImpact(
                finding_id="upcoming-works",
                amount=6500,
                status="known",
                description="Known works contribution; responsibility for payment remains to be confirmed.",
            ),
        ],
    )
