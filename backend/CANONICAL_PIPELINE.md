# Phase 2: canonical production pipeline

The authoritative specification is the ignored `private_specs/Rulebook.xlsx`.
Its reviewed SHA256 is `e806f6f9a6da0aa2f286e19e84cbae1c4b98d72f25a3ae8ea5380f778590d7b6`.
No workbook is read at runtime.

## Production flow

`POST /properties/analyze` validates all PDFs, anonymizes each, extracts from
anonymized text, verifies source identity and evidence quotes, and combines facts.
It calls `normalize_facts` before `AnalysisEngine.analyze`. Canonical objects select
`analyze_canonical`, which invokes only the three functions in `canonical_mvp.py`.
They return explicit evaluations and findings, with no external calls or clock reads.
Normalization or any earlier stage failing produces a sanitized error, not a
partial successful assessment. Original PDF text is not an input to normalization,
model extraction or rules. Returned canonical facts contain anonymized evidence.

The legacy direct-call engine remains isolated for existing fixture/API-library
consumers and their regression tests. Production does not convert canonical enums
back into legacy enums for rule execution. Mixed canonical/legacy engine inputs
are rejected. The legacy direct-call path is not the updated production evaluator.

## Evaluation records

`RuleEvaluation` contains evaluation_id, rule_id, applicable (true/false/null),
evaluation_status, rule_result, triggering_fact_ids/facts_used, calculation_inputs,
threshold_reason, missing_inputs, category, severity, source_validation_status,
and optional playback_template_id.

The requested application states are explicit:

| Application evaluation_status | Workbook vocabulary | Meaning |
|---|---|---|
| NOT_APPLICABLE | NOT_APPLICABLE | No supplied trigger or known non-comparable/excluded case |
| MISSING_INPUTS | NEEDS_INPUT | Evidence, applicability or caller-supplied policy is unresolved |
| EVALUATED_PASS | EVALUATED | The bounded comparison/check ran without producing a finding |
| TRIGGERED | EVALUATED | The bounded check produced an evidence-backed finding |

`workbook_evaluation_status` preserves the workbook vocabulary separately. Unknown
applicability is null rather than assumed true. A pass is not an approval of the
property. No new rule-result vocabulary is invented for A19/A30, which has no
sheet-23 result enum; its rule_result is null. B-rule results use the existing
sheet-23 registry. Playback IDs remain null: no renderer or new templates were added.

## Three supported families

- **A19+A30 floor area:** same measurement, asset/scope and resolved factual time;
  comparable positive m2 values; explicit caller-supplied absolute/relative tolerance.
  Unknown policy is MISSING_INPUTS. Known tax/living-area mismatch is NOT_APPLICABLE.
  Time representations that differ require clarification rather than inferred overlap.
- **B02 bounded contribution/allocation safeguard:** directly documented one-time
  unit contributions or special assessments, with source amount/locale, current
  evidence and due date. Project/association totals require explicit allocation and
  never become unit liability. Known unit amount remains distinct from buyer debt;
  UNKNOWN payer remains UNKNOWN. Full B01 exposure/funding/disruption and B02
  transaction-gate classification are not implemented. The bounded documented-cost
  finding uses NEEDS_VERIFICATION, not an invented ATTENTION/CRITICAL threshold.
- **B35 bounded evidence gap:** linked alteration/planning facts and an explicitly
  applicable required-document inventory. Missing inventory produces MISSING_INPUTS,
  not an inferred missing document. Recorded absence produces EVIDENCE_MISSING and
  neutral wording. Supplied evidence does not establish legal approval: authority
  validation remains an explicit missing policy. No new inventory is manufactured.

Completed works and past due dates do not establish payment. In those cases, a
current explicit unpaid status is required to include an outstanding contribution;
otherwise the evaluation requests current outstanding-payment evidence. Payment
records match the contribution's entity, project, amount semantics and factual
period/date; another obligation's payment cannot settle it. Conflicting payment or
payer evidence remains unresolved. No cost allocation or payment inference occurs.

## Traceability and response compatibility

`PropertyAssessment.canonical_facts` and `.rule_evaluations` expose the trace graph.
Each finding has rule_evaluation_id, rule_id, triggering_fact_ids, evidence and a
buyer action. Assessment validation rejects missing/mismatched links and evidence.
Document names remain in the existing documents/evidence fields. The example
`examples/canonical_pipeline_trace.json` is synthetic and uses explicit test policy;
it is neither Dresden nor a selected live case or production threshold policy.

Existing endpoint paths, finding type/id aliases, categories and numeric confidence
remain. New canonical_category carries the canonical category alongside the legacy
category. resolution_status is additive; existing status stays available. Existing
financial field names and legacy scalar shapes remain. Rule IDs for the canonical
works/planning families are now B02/B35; floor area retains A19+A30. Assessment and
finding IDs are deterministic within this version, not stable across engine versions.

Three distinct statuses are exposed:

- technical_processing_completed: all requested processing stages succeeded;
- rule_evaluation_completeness: complete/incomplete for only these three families;
- decision_readiness: unchanged safe NOT_DECISION_READY fallback.

The legacy processing_status remains unchanged for existing consumers. A successful
HTTP response may contain explicit MISSING_INPUTS evaluations. The result never
claims full rulebook or purchase readiness.

## Remaining decisions and limits

Julia's production area tolerances, temporal matching, field-specific freshness and
planning authority/applicability policies remain unresolved; defaults are not filled
from synthetic tests. Assessment dates are injected, never invented by the engine.
Live extraction metadata gaps are reported; extraction was not expanded to guess them.
Full B01–B38 evaluation, official approval/conflict handling, readiness,
recommendations, severity policies and playback remain outside this phase.
