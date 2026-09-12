# PDF processing integration

`POST /analyze` accepts one multipart `file` with a `.pdf` filename,
`application/pdf` content type, and PDF header. Empty files are rejected.
The application limit is 10 MiB; signature checking is not full PDF parsing.
The upstream OCR processor handles document decoding.

The endpoint returns HTTP 200 only after upstream completion, with
`document_received`, `processing_status`, `ready_for_extraction`, and
`anonymized_text`. It does not return original text, provider metadata, or
credential values. No extraction or property rules run yet.

## Verified provider contract

Source: https://developers.anymize.ai/ (checked 2026-09-12).

- Base URL: `https://app.anymize.ai/api`.
- Authentication: Bearer token loaded through existing Settings.
- Upload: `POST /ocr`, multipart field `file` containing the PDF.
- Poll: `GET /status/{job_id}`.
- Documented statuses: `processing`, `completed`.
- Completed text field: `anonymized_text_raw`.

The OCR section does not give a separate upload-response example. This adapter
requires a `job_id` consistent with the documented asynchronous workflow and
fails safely if it is absent. Confirm this with the provider or an authorized
deployment smoke test. Account access to OCR, provider upload limits, polling
guidance, and typical latency also remain unverified. Tests never call the API.

## Errors and timing

- 400: empty upload or multiple files.
- 415: wrong filename/content type or missing PDF header.
- 413: upload exceeds the application limit.
- 422: missing required multipart `file`.
- 503: anymize key is not configured.
- 502: upstream rejection, transport failure, or invalid/failed result.
- 504: upstream request timeout or 60-second processing deadline.

Polling uses a one-second interval and a 20-second HTTP request timeout inside
the overall deadline. Upload POSTs are not automatically retried. On timeout,
the provider job might still run; its cancellation and deduplication behavior
are not documented here. This milestone does not persist or resume jobs.

Production uses the existing environment-injected Secret Manager value.
No local `.env` is needed. Never log settings, authorization headers, upstream
bodies, or HTTP exception objects. Configure the Cloud Run request timeout to
allow for the processing deadline plus upload overhead.
