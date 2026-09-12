# Deterministic MVP analysis

```python
from app.services.analysis_engine import AnalysisEngine

assessment = AnalysisEngine().analyze(property_facts)
result = assessment.model_dump(mode="json")
```

Input is a list of validated `PropertyFact` objects for **one property**, across
multiple supplied documents. This service has no model, settings, network, or
FastAPI dependency. Existing endpoints remain available; there is no new route
or automatic rule execution in `/analyze` in this milestone.

`services/analysis_engine.py` validates facts, rejects conflicting fact IDs,
deduplicates repeated IDs, sorts input, executes three pure rules, and returns
the existing `PropertyAssessment`. Stable IDs and ordering make results
independent of input ordering. Inputs are not mutated.

Evidence now optionally includes `fact_id`, `document_id`, and `document_type`
alongside the existing source, excerpt, and page fields. Every generated finding
has a buyer action and all supporting quotes. Confidence is the minimum input
confidence; it is not a legal assessment or a calibrated rule probability.

## Provisional rules — Julia confirmation needed

1. **Floor area:** compare EXPOSE against FLOOR_PLAN facts from distinct
   documents. Trigger only when the absolute difference exceeds both 2 m² and
   2% of the smaller area. Thresholds are constructor parameters, not Golden
   Case constants. Explicitly different living/usable/internal measurement
   bases are excluded; unspecified bases are compared provisionally and the
   finding asks for verification. Numeric values must occur in the quotes.
   Confirm threshold, relevant document types, and treatment of unknown bases.

2. **Planned works:** require an explicit future/planned works phrase, a unit
   contribution phrase, and the numeric amount in the quote. Exclude estimates,
   negated/conditional statements, and already-paid contributions. A building
   total alone is insufficient. Rules recognize a limited English/German
   vocabulary and conservatively skip unsupported phrasing. No amount is
   inferred or prorated. Equal amounts across facts are grouped and all evidence
   retained; event IDs are needed to distinguish equal but separate works or
   revised amounts. Financial impacts are individually `known`, not proof that
   the purchaser must pay them. No overall cost total is calculated. Confirm
   attribution, certainty criteria, payment status, and event reconciliation.

3. **Planning documents:** require an explicitly existing alteration/extension
   AND an explicit statement that planning/compliance documents were not supplied.
   An extension alone or silence about paperwork does not trigger. A supplied
   documentation statement suppresses this provisional finding when evidence
   conflicts. Status remains unknown and needs verification; no illegality is
   inferred. The supplied facts are assumed to concern the same alteration.
   Confirm which documentation is required for each alteration, evidence-pack
   completeness, and how multiple alterations/conflicting document inventories
   should be matched. The engine does not determine legal requirements.

Severity retains the existing `high` (area/cost) and `medium` (planning) schema;
types remain `conflict`, `risk`, and `missing_information`. Confirm mapping to
Julia's critical/attention rulebook before changing public enums.

## Golden Case artifacts

- `tests/golden_case.py`: synthetic fixture factory.
- `examples/golden_case_facts.json`: complete canonical input facts.
- `examples/golden_case_assessment.json`: generated assessment, including all
  evidence and buyer actions.
- `tests/test_analysis_engine.py`: positive, negative, deterministic, duplicate,
  configurable-threshold, and no-network checks.

The case has 105 m² in a listing, 92 m² in a floor plan, a documented €6,500
upcoming unit contribution, an existing rear extension, and an explicit missing
planning-document statement. It produces three findings and one known EUR
financial impact. Example values exist only in fixtures and examples.
