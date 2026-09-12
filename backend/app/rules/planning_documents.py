from app.models.property_fact import PropertyFact
from app.rules.common import AnalysisPolicy, current, make_finding, traceable


def evaluate(facts: list[PropertyFact], policy: AnalysisPolicy):
    alterations = [f for f in facts if f.canonical_key in ("extension_reference", "alteration_reference")
                   and traceable(f) and f.project_id and f.status == "completed"]
    findings = []
    groups = {}
    for f in alterations:
        groups.setdefault((f.entity_id, f.scope, f.project_id), []).append(f)
    for (entity, scope, project), related in groups.items():
        refs = [f for f in facts if f.canonical_key in ("planning_documentation_reference", "planning_document_presence")
                and f.entity_id == entity and f.scope == scope and f.project_id == project and traceable(f)
                and current(f, policy)]
        missing = [f for f in refs if f.requirement_applicable is True
                   and f.document_priority in ("MUST_HAVE", "CONDITIONAL")
                   and f.document_presence == "missing"]
        # Conflicting inventories are unresolved, not evidence of definite absence.
        if not missing or any(f.document_presence in ("supplied", "not_applicable", "unclear") for f in refs):
            continue
        findings.append(make_finding(
            "A32+A33", related + missing, type="missing_evidence", category="planning",
            severity="NEEDS_VERIFICATION", status="unresolved",
            title="Applicable planning documentation not supplied",
            summary="An existing alteration/extension and an applicable required-document inventory are linked to the same entity and project. "
                    "Supporting planning/compliance documentation is not supplied. Status is unknown and needs verification; absence does not establish non-compliance.",
            uncertainty_reason="The inventory records documents not supplied, not the absence of permission or legal compliance.",
            buyer_action="Request the relevant planning permission and compliance documentation for this alteration or extension and verify applicability with the responsible authority.",
        ))
    return findings
