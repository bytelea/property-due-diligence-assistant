import asyncio
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.services.anymize import AnymizeService, get_anymize_service


PDF = b"%PDF-1.4\nsynthetic test content\n%%EOF\n"


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.settings_patch = patch(
            "app.services.anymize.get_settings",
            return_value=Settings(_env_file=None, anymize_api_key="placeholder"),
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.addCleanup(app.dependency_overrides.clear)
        self.calls = []
        self.responses = [
            httpx.Response(202, json={"job_id": "demo-job", "status": "processing"}),
            httpx.Response(200, json={"status": "processing"}),
            httpx.Response(200, json={
                "status": "completed",
                "anonymized_text_raw": "Owner: [[Name-demo]]. Area: 92 m².",
                "original_text": "Original text must not leave the service.",
                "metadata": {"private": "must not be returned"},
            }),
        ]
        self.service = AnymizeService(transport=httpx.MockTransport(self.handle_request))
        self.service.POLL_INTERVAL = 0
        app.dependency_overrides[get_anymize_service] = lambda: self.service

    def handle_request(self, request):
        self.calls.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def upload(self, content=PDF, filename="property.pdf", content_type="application/pdf"):
        with TestClient(app) as client:
            return client.post("/analyze", files={"file": (filename, content, content_type)})

    def test_success_uses_documented_http_contract(self):
        with self.assertLogs(level="DEBUG") as logs:
            response = self.upload()
        self.assertNotIn("placeholder", "\n".join(logs.output))
        self.assertNotIn("Original text", "\n".join(logs.output))
        self.assertNotIn("original_text", "\n".join(logs.output))
        self.assertNotIn("authorization", "\n".join(logs.output).lower())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "document_received": True,
            "processing_status": "completed",
            "ready_for_extraction": True,
            "anonymized_text": "Owner: [[Name-demo]]. Area: 92 m².",
        })
        self.assertEqual([(r.method, str(r.url)) for r in self.calls], [
            ("POST", "https://app.anymize.ai/api/ocr"),
            ("GET", "https://app.anymize.ai/api/status/demo-job"),
            ("GET", "https://app.anymize.ai/api/status/demo-job"),
        ])
        request = self.calls[0]
        self.assertEqual(request.headers["authorization"], "Bearer placeholder")
        self.assertIn('name="file"; filename="document.pdf"', request.content.decode())
        self.assertIn(PDF, request.content)
        self.assertNotIn("placeholder", response.text)
        self.assertNotIn("original_text", response.text)
        self.assertNotIn("Original text", response.text)
        self.assertNotIn("metadata", response.text)

    def test_invalid_uploads_never_call_anymize(self):
        for content, filename, mime, status in [
            (b"", "empty.pdf", "application/pdf", 400),
            (b"plain text", "fake.pdf", "application/pdf", 415),
            (PDF, "file.txt", "application/pdf", 415),
            (PDF, "file.pdf", "text/plain", 415),
        ]:
            with self.subTest(status=status, filename=filename):
                self.assertEqual(self.upload(content, filename, mime).status_code, status)
        with patch("app.main.MAX_PDF_BYTES", 8):
            self.assertEqual(self.upload().status_code, 413)
        self.assertEqual(self.calls, [])

    def test_missing_or_multiple_files(self):
        with TestClient(app) as client:
            self.assertEqual(client.post("/analyze").status_code, 422)
            response = client.post("/analyze", files=[
                ("file", ("a.pdf", PDF, "application/pdf")),
                ("file", ("b.pdf", PDF, "application/pdf")),
            ])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.calls, [])

    def test_missing_configuration(self):
        with patch("app.services.anymize.get_settings", return_value=Settings(anymize_api_key="")):
            self.assertEqual(self.upload().status_code, 503)
        self.assertEqual(self.calls, [])

    def test_upstream_errors_are_sanitized_and_not_retried(self):
        for status in (400, 401, 403, 429, 500, 302):
            with self.subTest(status=status):
                self.calls.clear()
                self.responses = [httpx.Response(status, text="placeholder upstream private details")]
                with self.assertLogs(level="DEBUG") as logs:
                    response = self.upload()
                self.assertEqual(response.status_code, 502)
                self.assertEqual(len(self.calls), 1)
                self.assertNotIn("placeholder", response.text)
                self.assertNotIn("private", response.text)
                self.assertNotIn("placeholder", "\n".join(logs.output))
                self.assertNotIn("authorization", "\n".join(logs.output).lower())

    def test_transport_errors_are_sanitized(self):
        for error, status in [
            (httpx.ReadTimeout("placeholder"), 504),
            (httpx.ConnectError("placeholder"), 502),
        ]:
            with self.subTest(status=status):
                self.responses = [error]
                response = self.upload()
                self.assertEqual(response.status_code, status)
                self.assertNotIn("placeholder", response.text)

    def test_invalid_job_responses(self):
        for response in [
            httpx.Response(200, text="not JSON"),
            httpx.Response(200, json=[]),
            httpx.Response(202, json={}),
            httpx.Response(202, json={"job_id": None}),
            httpx.Response(202, json={"job_id": 123}),
            httpx.Response(202, json={"job_id": ""}),
            httpx.Response(202, json={"job_id": "x" * 129}),
            httpx.Response(202, json={"job_id": "../elsewhere"}),
            httpx.Response(202, json={"job_id": "placeholder"}),
        ]:
            with self.subTest():
                self.calls.clear()
                self.responses = [response]
                result = self.upload()
                self.assertEqual(result.status_code, 502)
                self.assertEqual(len(self.calls), 1)
                self.assertNotIn("placeholder", result.text)

    def test_no_fallback_to_original_or_nonstandard_text_field(self):
        self.responses = [
            httpx.Response(202, json={"job_id": "demo-job"}),
            httpx.Response(200, json={
                "status": "completed",
                "original_text": "SYNTHETIC_PRIVATE_ORIGINAL",
                "anonymized_text": "SYNTHETIC_WRONG_FIELD",
            }),
        ]
        with self.assertLogs(level="DEBUG") as logs:
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        combined = response.text + "\n".join(logs.output)
        for forbidden in (
            "SYNTHETIC_PRIVATE_ORIGINAL", "SYNTHETIC_WRONG_FIELD",
            "original_text", "placeholder", "authorization",
        ):
            self.assertNotIn(forbidden.lower(), combined.lower())

    def test_failed_or_invalid_completed_result(self):
        for payload in [
            {"status": "failed", "error": "placeholder"},
            {"status": "unexpected"},
            {"status": "completed"},
            {"status": "completed", "anonymized_text_raw": ""},
            {"status": "completed", "anonymized_text_raw": "placeholder"},
            {"status": "completed", "anonymized_text_raw": {"text": "invalid"}},
        ]:
            with self.subTest():
                self.responses = [
                    httpx.Response(202, json={"job_id": "demo-job"}),
                    httpx.Response(200, json=payload),
                ]
                response = self.upload()
                self.assertEqual(response.status_code, 502)
                self.assertNotIn("placeholder", response.text)

    def test_processing_deadline(self):
        self.service.PROCESSING_TIMEOUT = 0.02

        async def pending(request):
            if request.method == "POST":
                return httpx.Response(202, json={"job_id": "demo-job"})
            await asyncio.sleep(1)
            return httpx.Response(200, json={"status": "processing"})

        self.service._transport = httpx.MockTransport(pending)
        self.assertEqual(self.upload().status_code, 504)
