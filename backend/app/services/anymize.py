"""Document API adapter. Contract: https://developers.anymize.ai/.

POST /api/ocr: multipart field `file`, Bearer authentication.
GET /api/status/{job_id}: poll for completed / anonymized_text_raw.
Never propagate upstream bodies, request objects, or exception text to callers.
"""

import asyncio
import re

import httpx

from app.config import get_settings


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
        api_key = get_settings().anymize_api_key.get_secret_value()
        if not api_key:
            raise AnymizeError(503, "Document processing is not configured.")
        try:
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
                    payload = self._payload(response)
                    job_id = payload.get("job_id")
                    if (
                        not isinstance(job_id, str)
                        or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", job_id)
                        or api_key in job_id
                    ):
                        raise AnymizeError(502, "Document processor returned an invalid job.")
                    while True:
                        payload = self._payload(await client.get(f"status/{job_id}"))
                        status = payload.get("status")
                        if status == "completed":
                            text = payload.get("anonymized_text_raw")
                            if not isinstance(text, str) or not text.strip() or api_key in text:
                                raise AnymizeError(502, "Document processor returned no usable result.")
                            return text
                        if status != "processing":
                            raise AnymizeError(502, "Document processing did not complete successfully.")
                        await asyncio.sleep(self.POLL_INTERVAL)
        except (TimeoutError, httpx.TimeoutException):
            raise AnymizeError(504, "Document processing timed out; completion is unconfirmed.") from None
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            raise AnymizeError(502, "Unable to communicate with the document processor.") from None

    @staticmethod
    def _payload(response: httpx.Response) -> dict:
        if response.status_code not in (200, 202):
            raise AnymizeError(502, "Document processor rejected the request.")
        try:
            payload = response.json()
        except ValueError:
            raise AnymizeError(502, "Document processor returned an invalid response.") from None
        if not isinstance(payload, dict):
            raise AnymizeError(502, "Document processor returned an invalid response.")
        return payload


def get_anymize_service() -> AnymizeService:
    return AnymizeService()
