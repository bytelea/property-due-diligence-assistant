from app.models.assessment import Finding
from app.models.property_fact import PropertyFact
from app.rules.common import evidence_links, matches, stable_id


def evaluate(facts: list[PropertyFact]) -> list[Finding]:
    alterations = [f for f in facts if f.key in ("alteration_reference", "extension_reference")
                   and isinstance(f.value, str) and f.value in f.evidence
                   and matches(r"extension|alteration|anbau|umbau", f.evidence)
                   and matches(r"exists|includes|added|built|completed|vorhanden|errichtet|gebaut|fertiggestellt", f.evidence)
                   and not matches(r"\bno\b|\bnot\b|proposed|planned|kein|nicht|geplant", f.evidence)]
    references = [f for f in facts if f.key == "planning_documentation_reference"
                  and isinstance(f.value, str) and f.value in f.evidence
                  and matches(r"planning|permission|compliance|baugenehmigung|genehmigungs|konformität", f.evidence)]
    missing = [f for f in references if matches(
        r"(?:not|never) (?:been )?(?:supplied|provided|submitted)|not available in (?:the )?(?:supplied )?pack|"
        r"nicht (?:vorgelegt|mitgeliefert|bereitgestellt)|fehlt|fehlen", f.evidence)]
    supplied = [f for f in references if f not in missing and matches(
        r"(?:was|were|is|are|has been|have been) (?:supplied|provided|submitted)|liegt vor|liegen vor|wurde vorgelegt", f.evidence)]
    if not alterations or not missing or supplied:
        return []
    supporting = alterations + missing
    return [Finding(
        id=stable_id("planning-documentation", supporting), severity="medium",
        type="missing_information", category="planning", title="Supporting planning documentation not supplied",
        summary="The supplied facts describe an existing alteration or extension and explicitly state that supporting "
                "planning/compliance documentation was not supplied. Status is unknown and needs verification; "
                "the absence of documents does not establish non-compliance.",
        evidence=evidence_links(supporting),
        buyer_action="Request the relevant planning permission and compliance documentation for the alteration or extension and verify it before proceeding.",
        confidence=min(f.confidence for f in supporting),
    )]
