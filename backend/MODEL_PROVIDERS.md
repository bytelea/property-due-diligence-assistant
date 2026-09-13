# Structured extraction providers

`MODEL_PROVIDER=vertex|anymize` selects the provider. The default remains Vertex.
Both adapters use the existing structured extraction schemas. Only anonymized OCR
text reaches classification and extraction. Evidence validation, normalization,
rules and API response contracts are unchanged.

## Anymize configuration

Set `MODEL_PROVIDER=anymize` and `ANYMIZE_MODEL` to an account-supported fixed model
ID or `auto`. Keep `ANYMIZE_API_KEY` injected from Secret Manager; the adapter
accesses it through Settings. No local environment file is required in production.

Requests use `https://app.anymize.ai/api/v1/llm/chat/completions` with structured
JSON schemas. The adapter does not use the deanonymizing anonymous-chat endpoint.
Account model availability should be confirmed through the provider model list.

## Bounded resilience

Each generation has at most three HTTP attempts inside the existing 60-second
overall deadline, including backoff. HTTP operations have an 18-second timeout.
Backoff is 0.5 seconds then 1 second.

Only HTTP 429, HTTP 500–599, transport timeouts, network errors and remote protocol
errors are retryable. For a fixed model, attempts one and two use that model;
following two transient failures, the final attempt uses `auto`. When configured
with `auto`, all three attempts use `auto`. A deadline may end processing sooner.

Authentication failures, 404, other rejected requests, malformed output, schema
errors and evidence failures do not trigger retries or fallback. There is no
cross-provider fallback to Vertex.

Fixed-model response IDs must match exactly. Auto responses must identify a
concrete model using a strict bounded identifier pattern; an `auto` response ID,
unsafe characters or a reflected key are rejected. The actual model is recorded
in safe diagnostics for each successful response. No mutable shared adapter
state or assessment-contract fields are added for this metadata.

## Safety and diagnostics

Logs contain only validated control metadata, fixed categories, timing, token
counts and validation flags. Never log keys, prompts, document text, response
bodies or exception details. Redirects are not followed. Existing schema,
placeholder and exact-evidence checks remain enforced after routing.

Exhausted HTTP availability failures remain sanitized 503 responses; timeouts
remain 504; invalid structured output remains 502. Routing does not change
readiness or deterministic property rules. Mocked tests do not prove live
account availability.
