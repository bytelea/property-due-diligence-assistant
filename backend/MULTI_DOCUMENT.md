# Multi-document property analysis

```bash
curl -X POST http://localhost:8080/properties/analyze \
  -F 'files=@listing.pdf;type=application/pdf' \
  -F 'files=@floor-plan.pdf;type=application/pdf'
```

Upload one or more PDFs under repeated `files` multipart fields. Each must have
a PDF filename, `application/pdf` content type, nonempty content and `%PDF-`
signature, and be at most 10 MiB (the existing per-document limit). This is
signature validation, not a full structural PDF parser. OCR handles decoding.
The batch limits are 10 uploaded files and 50 MiB of PDF content, including
duplicates. Proxy/platform limits can be lower and should be checked separately.

## Processing

`main.py` handles transport and closes uploads. `pdf_uploads.py` validates the
ENTIRE batch before external processing and creates request-scoped documents.
`PropertyAnalysisService` then runs, in stable document-ID order:

1. PDF bytes → existing `AnymizeService`.
2. Only its anonymized text → existing classification/extraction service.
3. Verify fact document IDs/types and evidence snippets against that document.
4. Combine all document facts → existing `AnalysisEngine`, once.
5. Attach document inventory and display names to the resulting assessment.

IDs are `doc-` plus SHA-256 of PDF bytes. The same bytes have the same ID across
requests, independently of filename or upload order. Identical content is
processed once per request; sorted filename aliases are retained. The first
sorted alias is used as the display name. Path components/control characters
are removed; filenames never reach the model or application logs. Content
changes produce a new ID. There is no cross-request cache or permanent PDF
storage. FastAPI may temporarily spool uploads; all upload handles are closed.

## Frontend response

The response is the existing `PropertyAssessment`, extended with:

- `documents`: IDs, display names, filename aliases, classified types, fact IDs,
  and per-document stage completion status. Documents with zero facts are included.
- Evidence `document_name`, alongside document ID/type, page, quote, and fact ID.
- `processing_status`: explicitly `incomplete` when the engine says
  `NOT_DECISION_READY`; this never overrides the engine's readiness judgment.
- Run metadata `processing_stages_completed` and `processed_document_count`.

`examples/multi_document_assessment.json` is a complete SYNTHETIC mocked example
with the three findings and EUR 6500 known unit contribution. It uses the existing
test policy and reviewed normalized facts, not a live model or production policy.

## Deliberate current limitations

No Julia thresholds, rulebook logic, or engine defaults changed. The production
factory uses `AnalysisEngine()` with its existing unconfigured policy. The
existing extractor also leaves required normalization metadata unresolved (entity,
measurement basis, dates, authority, applicability, page mapping, and so on).
Consequently the default endpoint can complete processing but return no material
findings and an explicitly incomplete assessment with uncertainties. This is
not a clean-property conclusion. Production rule activation requires the reviewed
normalization/policy work; test fixtures must not become production defaults.

No missing-document inference was added to extraction. Planning findings are
tested with explicit reviewed applicability/inventory facts; absence is handled
only by the existing deterministic rule. No document names are used to guess
property identity. The caller supplies documents for one property; unresolved
entity linkage is not guessed or merged.

The engine has no wall-clock reads. Stable output is verified for identical
mocked facts and explicit test policy, including reordered inputs. Live model
output may vary; content IDs do not make probabilistic model output deterministic.

## Failures and deployment

If any document fails anonymization, extraction, provenance validation, or engine
analysis, the request returns a fixed sanitized error and NO partial assessment.
Vertex permission/authentication failures preserve HTTP 503 and the existing
short provider-access log. Other known timeout errors retain 504; malformed
provider/provenance failures use 502. Invalid uploads use 400/413/415/422.
Neither upstream bodies nor exception details are returned.

Earlier provider jobs may already have run before a later failure; there is no
provider rollback, cancellation guarantee, or automatic batch retry. Processing
is sequential, using the existing per-stage deadlines. Deployment/proxy request
timeouts must allow the batch duration. No live requests were made for this
milestone; actual Vertex permissions/model availability remain unverified.

No Firestore, permanent PDF storage, new rules, or live policy thresholds were
added. Existing endpoints and tests are preserved.
