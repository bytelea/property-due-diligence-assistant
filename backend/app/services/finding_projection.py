"""Deterministic projection of unresolved evaluations; no new rule decisions."""
from uuid import NAMESPACE_URL, uuid5

from app.models.assessment import Evidence, Finding
from app.rules.canonical_mvp import RULEBOOK_VERSION


def verification_eligible(evaluation):
    return (evaluation.evaluation_status not in ('NOT_APPLICABLE', 'EVALUATED_PASS', 'TRIGGERED')
            and (evaluation.evaluation_status == 'MISSING_INPUTS' or evaluation.rule_result == 'NEEDS_VERIFICATION'))


def verification_finding(evaluation, facts_by_id):
    if not verification_eligible(evaluation) or not evaluation.triggering_fact_ids:
        return None
    facts = [facts_by_id[i] for i in evaluation.triggering_fact_ids]
    # Preserve the full trace contract; never invent evidence for unsupported facts.
    if any(not f.evidence.strip() for f in facts):
        return None
    title = f'{evaluation.category.value.replace("_", " ").title()} evidence needs verification'
    summary = 'Supplied evidence records ' + ', '.join(sorted({f.canonical_key for f in facts})) + '. '
    action = 'Request supporting documents and clarification of the unresolved inputs before purchase.'
    if evaluation.rule_id == 'B02':
        title = 'Planned works cost needs verification'
        summary = ('Planned works costs are documented, but the supplied evidence is insufficient '
                   'to establish an apartment-specific outstanding obligation or buyer liability. ')
        action = ('Ask who is responsible for payment and request the unit assessment, '
                  'current outstanding balance and payment schedule.')
    summary += evaluation.threshold_reason
    missing = ', '.join(evaluation.missing_inputs)
    if missing:
        summary += ' Unresolved inputs: ' + missing + '.'
    return Finding(
        id=str(uuid5(NAMESPACE_URL, 'verification:' + evaluation.evaluation_id)),
        rule_id=evaluation.rule_id, rule_evaluation_id=evaluation.evaluation_id,
        rulebook_version=RULEBOOK_VERSION, model_version='none:deterministic',
        type='missing_evidence', category={'AREA': 'floor_area', 'FINANCIAL': 'financial', 'LEGAL_TITLE': 'planning'}.get(evaluation.category, evaluation.category), canonical_category=evaluation.category,
        # Existing presentation class for uncertainty, not an inferred risk severity.
        severity='NEEDS_VERIFICATION', status='unresolved', title=title, summary=summary,
        buyer_action=action, linked_facts=evaluation.triggering_fact_ids,
        confidence=min(f.confidence for f in facts), confidence_reason='Source extraction confidence; the rule conclusion remains unresolved.',
        evaluation_status='NEEDS_INPUT', rule_result=evaluation.rule_result,
        threshold_reason=evaluation.threshold_reason, playback_template_id=evaluation.playback_template_id,
        source_validation_status=evaluation.source_validation_status,
        uncertainty_reason=missing or evaluation.threshold_reason,
        evidence=[Evidence(source=f'{f.document_type.value}: {f.document_id}', excerpt=f.evidence,
                           document_id=f.document_id, document_type=f.document_type.value,
                           fact_id=f.fact_id, page=f.page, relation=f.evidence_role,
                           source_authority=f.source_authority, extraction_confidence=f.confidence) for f in facts],
    )
