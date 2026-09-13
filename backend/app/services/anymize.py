"""Document API adapter. Contract: https://developers.anymize.ai/.

POST /api/ocr: multipart field `file`, Bearer authentication.
GET /api/status/{job_id}: poll for completed / anonymized_text_raw.
Never propagate upstream bodies, request objects, or exception text to callers.
"""

import asyncio
import logging
import re

import httpx

from app.config import get_settings


logger = logging.getLogger(__name__)


def log_diagnostic(context: dict, *, failed: bool = True) -> None:
    """Only locally constructed enums, HTTP integers and field-presence booleans.

    Never include job IDs, response keys/values, exception details or headers.
    """
    logger.log(logging.WARNING if failed else logging.INFO,
               "Anymize OCR diagnostic %s", dict(context))


class AnymizeError(Exception):
    """An error containing only a fixed, client-safe message."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class AnymizeService:
    BASE_URL = "https://app.anymize.ai/api/"
    PROCESSING_TIMEOUT = 60
    POLL_INTERVAL = 1

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def anonymize_pdf(self, content: bytes) -> str:
        diagnostic = {"stage": "ocr_start", "http_status": None, "category": "settings_error"}
        try:
            api_key = get_settings().anymize_api_key.get_secret_value()
            diagnostic["key_configured"] = bool(api_key)
            if not api_key:
                diagnostic["category"] = "missing_configuration"
                raise AnymizeError(503, "Document processing is not configured.")
            diagnostic["category"] = "transport_error"
            async with asyncio.timeout(self.PROCESSING_TIMEOUT):
                async with httpx.AsyncClient(
                    base_url=self.BASE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=httpx.Timeout(20),
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        "ocr", files={"file": ("document.pdf", content, "application/pdf")}
                    )
                    payload = self._payload(response, diagnostic)
                    diagnostic["category"] = "invalid_job_id"
                    job_id = payload.get("job_id")
                    if (
                        not isinstance(job_id, str)
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id)
                        or api_key in job_id
                    ):
                        raise AnymizeError(502, "Document processor returned an invalid job.")
                    diagnostic["category"] = "accepted"
                    log_diagnostic(diagnostic, failed=False)
                    while True:
                        diagnostic = {"stage": "ocr_poll", "http_status": None, "category": "transport_error"}
                        payload = self._payload(await client.get(f"status/{job_id}"), diagnostic)
                        status = payload.get("status")
                        # Never log an arbitrary provider status: it could contain content.
                        diagnostic["job_status"] = status if isinstance(status, str) and status in (
                            "processing", "completed", "failed", "queued", "pending", "cancelled"
                        ) else "unrecognized"
                        if status == "completed":
                            diagnostic["stage"] = "ocr_result"
                            diagnostic["category"] = "unusable_result"
                            text = payload.get("anonymized_text_raw")
                            if not isinstance(text, str) or not text.strip() or api_key in text:
                                raise AnymizeError(502, "Document processor returned no usable result.")
                            diagnostic["category"] = "completed"
                            log_diagnostic(diagnostic, failed=False)
                            return text
                        diagnostic["category"] = "unexpected_job_status"
                        if status not in ("pending", "processing"):
                            raise AnymizeError(502, "Document processing did not complete successfully.")
                        diagnostic["category"] = "processing"
                        log_diagnostic(diagnostic, failed=False)
                        await asyncio.sleep(self.POLL_INTERVAL)
        except AnymizeError:
            log_diagnostic(diagnostic)
            raise
        except (TimeoutError, httpx.TimeoutException):
            diagnostic["category"] = "timeout"
            log_diagnostic(diagnostic)
            raise AnymizeError(504, "Document processing timed out; completion is unconfirmed.") from None
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            log_diagnostic(diagnostic)
            raise AnymizeError(502, "Unable to communicate with the document processor.") from None
        except Exception:
            diagnostic["category"] = "unexpected_error"
            log_diagnostic(diagnostic)
            raise AnymizeError(502, "Unable to communicate with the document processor.") from None

    @staticmethod
    def _payload(response: httpx.Response, diagnostic: dict) -> dict:
        diagnostic["http_status"] = response.status_code
        diagnostic["category"] = "http_rejected"
        if response.status_code not in (200, 202):
            raise AnymizeError(502, "Document processor rejected the request.")
        diagnostic["category"] = "invalid_json"
        try:
            payload = response.json()
        except ValueError:
            raise AnymizeError(502, "Document processor returned an invalid response.") from None
        diagnostic["category"] = "invalid_envelope"
        if not isinstance(payload, dict):
            raise AnymizeError(502, "Document processor returned an invalid response.")
        diagnostic.update({
            "has_job_id": "job_id" in payload,
            "has_status": "status" in payload,
            "has_expected_text": "anonymized_text_raw" in payload,
            "has_alternate_text": "anonymized_text" in payload,
        })
        return payload


def get_anymize_service() -> AnymizeService:
    return AnymizeService()
