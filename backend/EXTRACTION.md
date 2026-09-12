# Structured property facts

Opt in with `POST /analyze?extract_facts=true`, uploading the same single PDF
multipart `file` as before. Without the flag the existing response is unchanged.
The optional `extraction` response object contains `document_id`,
`classification`, and `facts`. No final findings or cross-document rules run.

Pipeline:

1. `AnymizeService` produces anonymized text.
2. `DocumentClassificationService` selects an English `DocumentType`.
3. `PropertyFactExtractionService` produces and validates fact candidates.
4. `PropertyExtractionService` returns canonical facts with application-owned IDs.

The routes never pass uploaded PDF content to the model. Only the anonymizer's
completed text is used for classification and extraction. The internal
`AnonymizedDocument` type marks this boundary; it is not an anonymizer and must
not be constructed from raw text by other integrations.

## Configuration and structured output

Set `GEMINI_MODEL` to a Vertex AI model available in the configured
`GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`. No model is chosen silently.
The Cloud Run service identity needs Vertex AI access and the relevant API must
be enabled. Local use requires Application Default Credentials outside the
repository. No Gemini API key is used or added.

The adapter uses the Google Gen AI SDK's async Vertex client and JSON schema
output (`response_mime_type=application/json`, `response_json_schema`).
Reference: https://googleapis.github.io/python-genai/.

Prompts: `app/prompts/property_extraction.py`.
Schemas: `DocumentClassification` and `FactCandidates` in
`app/models/property_fact.py`; `model_json_schema()` gives the exact schemas.
Both responses are parsed and validated again by Pydantic; prose, unknown
fields, invalid types, and out-of-range confidence are rejected.

## Evidence and scope

- All evidence must occur verbatim in the anonymized input. Reference values
  must also be present in the evidence. Numeric values must match a number in
  the quote, allowing English/German formatting. This verifies source grounding,
  not the model's complete semantic interpretation.
- Keys: `floor_area`, `planned_works_cost`, `alteration_reference`,
  `extension_reference`, `planning_documentation_reference`.
- Canonical units are `m2` and `EUR`; reference facts use null units.
- Silence is not proof of missing documentation. An absence reference must be
  explicitly supported by the document. Compliance is never inferred.
- Quotes retain area measurement basis and cost allocation context. Future
  comparison must distinguish living/usable areas and unit/building costs;
  these distinctions are not yet separate normalized fields.
- Plain anymize text has no trusted page mapping, so `page` is null internally
  (null fields are omitted from the HTTP response). No page numbers are invented.
- Fact IDs are stable for identical facts within the same document ID. Uploads
  receive new document IDs; there is no persistence or cross-upload deduplication.
- Evidence stays in its original language with anonymization placeholders;
  field names, document types, and units are canonical English identifiers.

## Limits and remaining checks

The extraction input limit is 100,000 characters; at most 100 facts are accepted
per document. There is no chunking yet. Each of the two model calls has a
60-second deadline. Allow upload/anonymization time plus both calls in the
deployment request timeout. Upstream errors use fixed messages without model
content or credentials. Model responses are untrusted; evidence validation does
not prove that a numeric fact is semantically correct or that a document has
been fully anonymized by the upstream provider.

Tests mock both model responses and SDK calls and preserve the original API
tests. No real model requests were made. Model availability, project permissions,
live structured-output compatibility, and accuracy on real anonymized documents
still require a deployment smoke test.
