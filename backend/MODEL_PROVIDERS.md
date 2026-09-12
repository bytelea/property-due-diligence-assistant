# Structured extraction providers

Provider selection is explicit through `MODEL_PROVIDER=vertex|anymize`; the default
is `vertex`, preserving existing deployments. Errors never trigger an automatic
provider switch. Both adapters implement the existing `StructuredModelClient`
protocol (`generate(instruction, content, schema) -> JSON string`). The only
extraction wiring change selects that interface through `get_structured_model()`.
Classification, extraction schemas, evidence validation, normalization, rules,
endpoint paths, response models and frontend contracts are unchanged.

## Verified official API contract

Checked 2026-09-12:

- [API getting started](https://anymize.ai/api-docs): LLM base URL
  `https://app.anymize.ai/api/v1/llm` and Bearer authentication.
- [Chat API](https://anymize.ai/api-docs/chat):
  `POST /api/v1/llm/chat/completions`, standard messages, JSON output,
  `response_format.type=json_schema` with `json_schema.name` and `json_schema.schema`.
  Its Models section lists `gemini-2.5-flash` as a Google model ID.
- The same Chat API documentation explicitly supports pre-anonymized text on the
  standard endpoint with instructions to preserve double-bracket placeholders.

The request uses the standard endpoint and Gemini model ID above, with the existing
Pydantic JSON schema, temperature 0 and streaming disabled. This is a configured
model, not an automatically chosen fallback. The adapter requires the response's
model to match the configured model; provider-side substitutions fail safely.

The general marketing page shows alternative URLs/prefixed model names. This
implementation follows the dedicated API documentation's endpoint and model-ID
example. Account-specific model availability and Gemini's acceptance of every
schema keyword remain deployment smoke-test items. No authenticated live calls
were made during implementation; the API/model contracts are documentation-verified,
not a claim of successful inference with this account.

## Configuration

To use Anymize without Vertex IAM:

```dotenv
MODEL_PROVIDER=anymize
ANYMIZE_MODEL=gemini-2.5-flash
```

Keep the existing `ANYMIZE_API_KEY` Secret Manager injection. It is accessed only
through `get_settings().anymize_api_key.get_secret_value()`. Do not put its value
in source, documentation, example files or logs. The setting ANYMIZE_MODEL has no
implicit default; an empty model/key returns sanitized 503. Restart/redeploy after
changing environment configuration, as settings are cached.

To keep Vertex:

```dotenv
MODEL_PROVIDER=vertex
```

The existing GEMINI_MODEL, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION and Cloud Run
service identity/IAM configuration still apply. The Vertex implementation and its
sanitized authentication handling are retained. Anymize selection does not create
a Vertex client or require its IAM permissions.

## Privacy and error behavior

Only the OCR adapter receives PDFs. Its anonymized output feeds classification and
extraction. No original_text, job IDs or deanonymization mappings are included in
model requests. The model adapter never calls the anonymous chat endpoint or a
deanonymization endpoint. It adds placeholder-preservation instructions, rejects
new/altered double-bracket tokens and validates JSON against the existing schema.
Existing extraction checks still require verbatim evidence from anonymized input.

The adapter returns only assistant content, never raw provider metadata. Empty,
malformed, refused, truncated or schema-invalid output is rejected. A reflected key
is rejected even after JSON escape decoding. HTTP redirects are not followed;
Authorization cannot be forwarded to an alternate host through a redirect.
Application errors/logs contain no request bodies, Authorization headers, response
bodies or exception details. Access failures emit only a fixed short warning.

- 503: missing configuration, authentication/access failure, rate limit,
  unavailable model/service, or unexpected model substitution.
- 504: request/overall timeout.
- 502: other request failure or invalid structured response.

The 60-second overall deadline and 55-second HTTP timeout bound each model call.
There are no retries or alternate-provider attempts. Check account-side logging,
retention and fallback settings in the Anymize console separately; application
logging policy does not configure provider-side retention.

The fallback removes the Vertex dependency for model calls. Existing missing
canonical metadata/policy can still yield MISSING_INPUTS and NOT_DECISION_READY;
this milestone does not change extraction or rule completeness.
