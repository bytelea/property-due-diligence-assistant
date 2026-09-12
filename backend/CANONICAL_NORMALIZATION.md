# Phase 1 canonical schema and normalization

Source: `private_specs/Rulebook.xlsx`, sheets 03, 08, 17, 18, 19 and 23.
Reviewed workbook SHA256: `e806f6f9a6da0aa2f286e19e84cbae1c4b98d72f25a3ae8ea5380f778590d7b6`.
The workbook is private and is not a runtime dependency.

## Boundary

```python
from app.services.normalization import normalize_facts

# extraction contains evidence quoted only from anonymized text.
canonical_facts = normalize_facts(extraction.facts)
# Future canonical rule evaluator consumes canonical_facts.
```

`CanonicalPropertyFact` is a `PropertyFact` subclass with strictly canonical enums.
Normalization revalidates its inputs, returns new objects, preserves order and IDs,
and is idempotent. It performs no IO, model calls, rule evaluation, document
inventory inference, authority ranking, date synthesis or financial allocation.

The existing routes and legacy rules continue to use their existing facts. The
canonical boundary is callable but deliberately not substituted into the legacy
engine: uppercase canonical values would change that engine's comparisons. This
phase does not claim that live extraction now supplies missing page, scope,
identity, date or authority metadata. A later migration must enrich those inputs
from anonymized evidence and connect the canonical evaluator explicitly.

## Compatibility

Existing fact aliases, lowercase values, evidence strings and numeric confidence
remain available. New uppercase enums are accepted by PropertyFact. Normalization
maps only enumerated spellings: `WEG` to `OWNERS_ASSOCIATION`, `unit` to `UNIT`,
`living_area` to `LIVING_AREA`, `one-time` to `ONE_TIME`, and evidence roles
`supporting/contradicting/contextual` to `SUPPORTS/CONTRADICTS/CONTEXT`.

Legacy `reserve`, `balance` and `unit_owner` have no unambiguous canonical mapping.
They remain valid legacy inputs but normalization raises a sanitized error naming
only the field. The caller must supply an evidenced canonical classification;
normalization never substitutes a buyer, reserve balance or reserve withdrawal.

Absent optional metadata stays null. Explicit unknown enum values become UNKNOWN.
Only square-metre spelling aliases are unified. Monetary strings are parsed only
when currency and locale are supplied; raw spelling and sign are preserved.
Without a locale, a monetary string remains a string. No allocation or currency
conversion is performed. Source authority is carried through, never ranked.

New date fields preserve document, factual and current-status dates independently.
Period endpoints are not inferred from a free-text period; reversed endpoints are
rejected. Layout, claim, public-law and condition-evidence states are independent
fields, not findings or diagnoses. Structured JSON values are supported without
inventing a range/address schema that the workbook does not define.

Finding evaluation metadata is optional until later evaluation is implemented.
When a rule result is supplied, its vocabulary is checked against sheet 23 column G
for that rule ID. This registry contains no triggers, calculations or thresholds.
Legacy finding aliases and scalar financial impact fields remain unchanged;
additional known_financial_impacts and possible_financial_impacts arrays can hold
independent amounts without changing those existing scalar field shapes.

`technical_processing_completed` is populated after successful multi-document
processing independently of decision_readiness. Existing processing_status and the
safe NOT_DECISION_READY fallback are retained for compatibility.

## Questions intentionally left open

- Sheet 19 includes UNSUPPORTED_CLAIM as a finding type, whereas 03/08 omit it.
  It is represented only as the explicit claim/result state, not enabled as a new
  emitted finding type.
- Catalog claim/planning states differ from rule-specific sheet 23 result states.
  These remain separate vocabularies; no automatic mapping is assumed.
- Canonical key spellings for the full field catalog and structured value shapes
  need agreement; no invented global key enum is imposed.
- Source-authority precedence, area thresholds, applicability policies and
  reasoning-confidence assignment remain later policy work.
- No original non-anonymized wording is retained to satisfy the workbook's
  optional original-text audit recommendation.

No B01–B38 evaluator, playback renderer, readiness rule, recommendation, benchmark,
or buyer-liability inference was added. Existing rulebook-version metadata is
unchanged because the running rules still implement the previous MVP behavior.
