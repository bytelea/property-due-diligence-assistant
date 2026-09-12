# Locked-rulebook MVP engine

Source: private workbook `backend/private_specs/Rulebook.xlsx`. It is read-only
and is not required at runtime. Its SHA-256 is recorded in rule output; tests
and production do not open the workbook or call any provider.

## Implemented workbook scope

Read contracts first: 03_Canonical_Semantics, 08_Output_Contract, 19_Finding_Schema.
Then reviewed 02_Decision_Register, 04_Rulebook_A_B, 05_Golden_Test_Case,
06_Adversarial_Tests, 07_Input_Checklist, 11_Dresden_Evidence,
15_Property_Doc_Checklist and 18_Canonical_Field_Catalog.

Implemented only the three requested families:

- A01/A03, A19/A30: explicitly comparable area facts (scope/entity/type/time/status).
- A04, A08-A11, A13, A16-A18, B01/B02: unit contribution semantics and provenance;
  no project-total allocation, recurring-cost arithmetic, or actual-to-plan conversion.
- A32/A33 and checklist planning applicability: explicit, current, linked missing
  required evidence for an existing alteration; never an illegality conclusion.
- A28/A29, B21/B22, AB01: source traceability, extraction uncertainty, buyer actions,
  reproducible matching order. B19 is limited to a current-status uncertainty
  message; no separate full-project status-gap finding has been implemented.

These are scoped implementations, not claims that every behavior in those broad
rule families or every Dresden expectation is complete.

## Canonical facts and compatibility

`PropertyFact` accepts canonical_key, extraction_confidence, source_document_id,
plus evidence_snippet. Existing key/confidence/document_id/evidence remain aliases
in serialized output for consumers; inconsistent aliases fail validation.

Metadata includes currency, measurement_type, scope, entity_id, project_id,
status, amount_type, frequency, factual_date, factual_period, document_date,
evidence_role, source_authority, document_applicability, document_presence,
document_priority, requirement_applicable, payer_status, payment_status, raw_value,
number_format, and exact allocation numerator/denominator/basis. Unknown metadata
is retained as unknown/null; it is never inferred from document names or snippets.
Only an explicit normalization stage or reviewed fixture should resolve it.

Legacy extraction still works but does not establish these semantics. Its facts
therefore do not automatically qualify for material deterministic findings. No
live multi-document integration was added. Original non-anonymized text is not
stored despite the workbook's recommended audit wording field: evidence snippets
must remain anonymized, as required by the application security boundary.

## Pure engine and explicit policy

```python
from datetime import date, datetime, timezone
from app.services.analysis_engine import AnalysisEngine

# EXAMPLE TEST policy, not locked production defaults:
engine = AnalysisEngine(
    area_absolute_tolerance=2.0,
    area_relative_tolerance=0.02,
    as_of=date(2026, 9, 12),
    freshness_days_by_key={"planned_works_cost": 365,
                           "planning_documentation_reference": 365},
    analysis_timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
)
assessment = engine.analyze(normalized_facts)
```

Freshness supports independent per-canonical-key windows; an explicit
max_document_age_days is retained as a caller-selected fallback, never a locked
default. Tolerances and freshness are explicitly open in decisions D13/D14. Unconfigured
area policy disables material area conflicts; unconfigured evaluation date or
freshness disables current known-cost and missing-document findings. The engine
reports these gaps instead of guessing. No clock reads: the caller supplies the
audit timestamp. Missing timestamps are null and explicitly reported.

Area conflicts require matching known measurement type, scope, entity, project,
factual date/period, status and amount semantics across distinct documents.
No conversion between tax/advertised/living/usable area occurs. Unknowns do not
match just because both are unknown. Materiality exceeds both supplied absolute
and relative thresholds. Source authority is preserved, not silently used to
replace one value; precedence remains proposed in D12.

Known financial impacts require a directly quoted, correctly formatted/signed
amount, EUR currency, unit scope, identified unit and project, contribution amount
type, one-time frequency, future/current explicit factual date, recent source,
and planned/approved/ordered/ongoing status. Historical actuals, budgets,
estimates, paid/cancelled/completed items and WEG totals cannot qualify.
The raw monetary token and source number format are required to audit parsing.
Duplicate evidence for the same project/time obligation is grouped; unequal
amounts for that obligation are not resolved by guessing. Equal amounts for
separate projects remain separate. No grand total or prorated liability is inferred.
Buyer/seller payer remains unknown unless explicit in the normalized facts.

Planning requires completed alteration/extension facts plus matching entity,
scope and project inventory facts: applicability true, MUST_HAVE/CONDITIONAL,
missing, recent, and traceable. NICE_TO_HAVE and not-applicable documents do not
trigger. Silence or an extension alone is insufficient. Contradictory inventories
are not resolved by assuming an absence. Legal applicability is supplied by the
reviewed context, not inferred from generic extension words.

Every material finding requires source document, page, snippet, document date,
resolved authority, supporting/contradicting relation and nonzero extraction
confidence. No guessed page numbers. OCR uncertainty is retained; uncertain
findings use NEEDS_VERIFICATION rather than critical severity.

## Output

Existing assessment fields and routes remain. Finding type now uses the locked
vocabulary, including missing_evidence and documented_fact. Legacy demo data
was migrated to the same type vocabulary; no endpoint was removed.

Outputs add finding_id/finding_type/facts_used/explanation aliases, rule IDs,
linked facts, scope/entity/project, uncertainty, evidence roles/authority and
separate confidence rationale; known_additional_costs/potential_costs, summary,
run metadata and decision_readiness are provided. Existing financial_impacts
is retained. Reasoning confidence is not calibrated; the numeric compatibility
field retains the minimum extraction score and the reason explains this.

Full property/address context and full readiness/recommendation cannot be proven
from this three-rule subset. No address is fabricated. Readiness conservatively
remains NOT_DECISION_READY with an explicit partial-assessment explanation.

## Case separation and regression coverage

- Dresden D01-D16 is the PRIMARY REGRESSION case. The coverage manifest in
  `examples/dresden_regression_coverage.json` tracks each expectation separately.
  Workbook-derived semantic probes cover no-false-area/no-false-liability gates;
  they are NOT an end-to-end Dresden extraction or all-16-findings acceptance run.
- `tests/synthetic_mvp.py` and `examples/synthetic_mvp_*.json` are SYNTHETIC S01
  and unit-contribution/planning breadth fixtures. They contain 105/92/6500.
- No live-demo case has been selected here. The legacy tests/golden_case.py is
  only a deprecated compatibility import for the synthetic fixture.

Existing test scenarios are retained with assertions migrated to the locked
vocabulary and normalized-metadata inputs instead of English keyword heuristics.
Additional adversarial tests cover mismatched type/scope/entity/time/status,
unknown metadata, planned vs actual, project/unit separation, approved vs completed,
German formatting/signs, distinct allocation bases, evidence applicability,
rounding, OCR uncertainty, provenance, aliases and deterministic output.

## Clarifications and deliberately deferred work

1. D13/D14: production freshness windows and field-specific tolerances.
2. D12: fact-specific authority ranking is proposed, not a numeric ordering.
3. D15: exact scenario applicability and completeness of required documents.
4. Severity thresholds and calibrated reasoning-confidence policy are not locked.
5. Period interval overlap, ongoing-work obligations without a due date, allocation
   formulas, project aliases and revision matching need explicit rules; no fuzzy matching.
6. Some 11_Dresden_Evidence page cells are Excel date serials rather than usable
   page ranges. Original page/crop evidence is needed to repair provenance. The
   workbook was not changed, and serials were not used as page numbers.
7. Full Dresden D01-D16 detection, remaining rules, reserve/energy/title/lease
   interpretation, buyer fit, recommendations, full document completeness, and
   live multi-document uploads are deliberately not implemented.
