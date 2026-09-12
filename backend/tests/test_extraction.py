import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.genai import errors
from pydantic import ValidationError

from app.config import Settings
from app.main import app
from app.models.property_fact import (
    AnonymizedDocument, DocumentClassification, DocumentType, FactCandidates, PropertyFact,
)
from app.services.anymize import get_anymize_service
from app.services.extraction import PropertyExtractionService, get_extraction_service, number_occurs_in_evidence
from app.services.structured_model import ExtractionError, GeminiStructuredModel


TEXT = (
    "Wohnfläche: 105 m². Geplante Dacharbeiten: Anteil dieser Wohnung 6.500 EUR. "
    "Rear extension added. Planning permission documentation was not supplied. "
    "Owner: [[Name-demo]]."
)
FACTS = [
    {"key": "floor_area", "value": 105, "unit": "m2", "evidence": "Wohnfläche: 105 m².", "confidence": 0.98},
    {"key": "planned_works_cost", "value": 6500, "unit": "EUR", "evidence": "Geplante Dacharbeiten: Anteil dieser Wohnung 6.500 EUR.", "confidence": 0.95},
    {"key": "extension_reference", "value": "Rear extension added.", "unit": None, "evidence": "Rear extension added.", "confidence": 0.9},
    {"key": "planning_documentation_reference", "value": "Planning permission documentation was not supplied.", "unit": None, "evidence": "Planning permission documentation was not supplied.", "confidence": 0.9},
]


def mock_model(facts=None, classification="EXPOSE"):
    model = SimpleNamespace(generate=AsyncMock(side_effect=[
        json.dumps({"document_type": classification, "confidence": 0.9}),
        json.dumps({"facts": FACTS if facts is None else facts}),
    ]))
    return model


class ExtractionTests(unittest.IsolatedAsyncioTestCase):
    def test_localized_numbers_preserve_decimals(self):
        for text in ("6.500 EUR", "6,500 EUR", "6 500 EUR", "6.500,00 EUR", "6,500.00 EUR"):
            self.assertTrue(number_occurs_in_evidence(6500, text))
        self.assertTrue(number_occurs_in_evidence(92.5, "Wohnfläche 92,5 m²"))
        self.assertFalse(number_occurs_in_evidence(925, "Wohnfläche 92,5 m²"))

    async def test_canonical_facts_and_exact_evidence(self):
        model = mock_model()
        result = await PropertyExtractionService(model).extract(AnonymizedDocument(document_id="doc-demo", text=TEXT))
        self.assertEqual(len(result.facts), 4)
        self.assertEqual(result.classification.document_type, DocumentType.EXPOSE)
        for fact in result.facts:
            self.assertEqual(fact.document_id, "doc-demo")
            self.assertIsNone(fact.page)
            self.assertIn(fact.evidence, TEXT)
            self.assertTrue(fact.fact_id)
        self.assertEqual(result.facts[1].value, 6500)
        calls = model.generate.await_args_list
        self.assertEqual(calls[0].args[2], DocumentClassification)
        self.assertEqual(calls[1].args[2], FactCandidates)
        self.assertTrue(all(call.args[1] == TEXT for call in calls))
        self.assertNotIn("original_text", result.model_dump_json())

    async def test_no_facts_is_valid_and_all_document_types_supported(self):
        self.assertEqual(len(DocumentType), 13)
        for document_type in DocumentType:
            result = await PropertyExtractionService(mock_model([], document_type.value)).extract(
                AnonymizedDocument(document_id="doc", text="No relevant property facts.")
            )
            self.assertEqual(result.facts, [])

    async def test_hallucinated_evidence_or_value_is_rejected(self):
        for change in [
            {"evidence": "Fabricated quote."},
            {"value": 999},
            {"unit": "EUR"},
            {"confidence": 1.2},
            {"value": "105"},
            {"original_text": "SYNTHETIC_PRIVATE_MARKER"},
            {"page": 7},
        ]:
            with self.subTest(change=list(change)):
                fact = {**FACTS[0], **change}
                with self.assertRaises(ExtractionError) as error:
                    await PropertyExtractionService(mock_model([fact])).extract(
                        AnonymizedDocument(document_id="doc", text=TEXT)
                    )
                self.assertEqual(error.exception.status_code, 502)
                self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", str(error.exception))

    async def test_reference_value_must_be_in_evidence(self):
        fact = {**FACTS[2], "value": "Extension is legally compliant."}
        with self.assertRaises(ExtractionError):
            await PropertyExtractionService(mock_model([fact])).extract(AnonymizedDocument(document_id="doc", text=TEXT))

    async def test_malformed_json_and_invalid_classification(self):
        for output in ['not json', '{"document_type":"UNKNOWN","confidence":0.9}', '{"document_type":"EXPOSE","confidence":2}']:
            model = SimpleNamespace(generate=AsyncMock(return_value=output))
            with self.assertRaises(ExtractionError):
                await PropertyExtractionService(model).extract(AnonymizedDocument(document_id="doc", text=TEXT))
        model = mock_model()
        model.generate.side_effect = [json.dumps({"document_type": "OTHER", "confidence": 0.5}), "not json"]
        with self.assertRaises(ExtractionError):
            await PropertyExtractionService(model).extract(AnonymizedDocument(document_id="doc", text=TEXT))

    async def test_stable_ids_and_deduplication(self):
        results = []
        for _ in range(2):
            results.append(await PropertyExtractionService(mock_model([FACTS[0], FACTS[0]])).extract(
                AnonymizedDocument(document_id="doc", text=TEXT)
            ))
        self.assertEqual(len(results[0].facts), 1)
        self.assertEqual(results[0].facts[0].fact_id, results[1].facts[0].fact_id)

    async def test_empty_input_and_limits(self):
        model = mock_model()
        with self.assertRaises(ExtractionError):
            await PropertyExtractionService(model).extract(AnonymizedDocument(document_id="doc", text=" "))
        model.generate.assert_not_awaited()
        with self.assertRaises(ValidationError):
            AnonymizedDocument(document_id="doc", text="x" * 100_001)


class GeminiAdapterTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, model="test-model"):
        return Settings(_env_file=None, gemini_model=model)

    async def test_vertex_json_schema_and_anonymized_input(self):
        with patch("app.services.structured_model.get_settings", return_value=self.settings()), patch("app.services.structured_model.genai.Client") as factory:
            client = MagicMock()
            client.models.generate_content = AsyncMock(return_value=SimpleNamespace(text='{"facts":[]}'))
            factory.return_value.aio.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.aio.__aexit__ = AsyncMock(return_value=False)
            result = await GeminiStructuredModel().generate("instruction", TEXT, FactCandidates)
            self.assertEqual(result, '{"facts":[]}')
            self.assertTrue(factory.call_args.kwargs["vertexai"])
            self.assertNotIn("api_key", factory.call_args.kwargs)
            args = client.models.generate_content.call_args.kwargs
            self.assertEqual(args["contents"], TEXT)
            self.assertEqual(args["config"].response_mime_type, "application/json")
            self.assertEqual(args["config"].response_json_schema, FactCandidates.model_json_schema())

    async def test_missing_config_does_not_call_provider(self):
        with patch("app.services.structured_model.get_settings", return_value=self.settings("")), patch("app.services.structured_model.genai.Client") as factory:
            with self.assertRaises(ExtractionError) as error:
                await GeminiStructuredModel().generate("instruction", TEXT, FactCandidates)
            self.assertEqual(error.exception.status_code, 503)
            factory.assert_not_called()

    async def test_provider_errors_are_sanitized(self):
        for exception, status in [(RuntimeError("SYNTHETIC_PRIVATE_MARKER"), 502), (TimeoutError("SYNTHETIC_PRIVATE_MARKER"), 504)]:
            with patch("app.services.structured_model.get_settings", return_value=self.settings()), patch("app.services.structured_model.genai.Client", side_effect=exception):
                with self.assertRaises(ExtractionError) as error:
                    await GeminiStructuredModel().generate("instruction", TEXT, FactCandidates)
                self.assertEqual(error.exception.status_code, status)
                self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", str(error.exception))

    async def test_access_failures_have_only_a_fixed_log_message(self):
        failures = [
            errors.ClientError(code=code, response_json={"error": {"message": "SYNTHETIC_PRIVATE_MARKER", "details": "Authorization: Bearer synthetic-test-only"}})
            for code in (401, 403)
        ] + [DefaultCredentialsError("SYNTHETIC_PRIVATE_MARKER"), RefreshError("SYNTHETIC_PRIVATE_MARKER")]
        for failure in failures:
            with self.subTest(failure_type=type(failure).__name__), patch("app.services.structured_model.get_settings", return_value=self.settings()), patch("app.services.structured_model.genai.Client") as factory:
                client = MagicMock()
                client.models.generate_content = AsyncMock(side_effect=failure)
                factory.return_value.aio.__aenter__ = AsyncMock(return_value=client)
                factory.return_value.aio.__aexit__ = AsyncMock(return_value=False)
                with self.assertLogs("app.services.structured_model", level="WARNING") as logs:
                    with self.assertRaises(ExtractionError) as error:
                        await GeminiStructuredModel().generate("instruction", TEXT, FactCandidates)
                self.assertEqual(error.exception.status_code, 503)
                self.assertEqual(str(error.exception), "Property extraction provider is unavailable.")
                self.assertTrue(error.exception.__suppress_context__)
                self.assertEqual(len(logs.records), 1)
                self.assertEqual(logs.records[0].getMessage(), "Vertex AI provider access failed.")
                self.assertIsNone(logs.records[0].exc_info)
                self.assertEqual(logs.records[0].args, ())

    async def test_adc_initialization_failure_is_sanitized(self):
        with patch("app.services.structured_model.get_settings", return_value=self.settings()), patch("app.services.structured_model.genai.Client", side_effect=DefaultCredentialsError("SYNTHETIC_PRIVATE_MARKER")):
            with self.assertLogs("app.services.structured_model", level="WARNING") as logs:
                with self.assertRaises(ExtractionError) as error:
                    await GeminiStructuredModel().generate("instruction", TEXT, FactCandidates)
            self.assertEqual(error.exception.status_code, 503)
            self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", str(error.exception) + str(logs.output))


class ExtractionRouteTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_vertex_access_errors_return_sanitized_503(self):
        app.dependency_overrides[get_anymize_service] = lambda: SimpleNamespace(anonymize_pdf=AsyncMock(return_value=TEXT))
        app.dependency_overrides[get_extraction_service] = lambda: PropertyExtractionService()
        for code in (401, 403):
            with self.subTest(code=code), patch("app.services.structured_model.get_settings", return_value=Settings(gemini_model="test-model")), patch("app.services.structured_model.genai.Client") as factory:
                provider = MagicMock()
                provider.models.generate_content = AsyncMock(side_effect=errors.ClientError(code=code, response_json={"error": {"message": "SYNTHETIC_PRIVATE_MARKER"}}))
                factory.return_value.aio.__aenter__ = AsyncMock(return_value=provider)
                factory.return_value.aio.__aexit__ = AsyncMock(return_value=False)
                with self.assertLogs("app.services.structured_model", level="WARNING") as logs, TestClient(app) as client:
                    response = client.post("/analyze?extract_facts=true", files={"file": ("property.pdf", b"%PDF-test", "application/pdf")})
                    self.assertEqual(client.get("/health").status_code, 200)
                    self.assertEqual(client.get("/demo-assessment").status_code, 200)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "Property extraction provider is unavailable."})
                self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", response.text + str(logs.output))

    def test_opt_in_extracts_only_anonymizer_output(self):
        anonymizer = SimpleNamespace(anonymize_pdf=AsyncMock(return_value=TEXT))
        model = mock_model()
        app.dependency_overrides[get_anymize_service] = lambda: anonymizer
        app.dependency_overrides[get_extraction_service] = lambda: PropertyExtractionService(model)
        with TestClient(app) as client:
            response = client.post("/analyze?extract_facts=true", files={"file": ("property.pdf", b"%PDF-original synthetic bytes", "application/pdf")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["extraction"]["facts"]), 4)
        for call in model.generate.await_args_list:
            self.assertEqual(call.args[1], TEXT)
            self.assertNotIn("original synthetic bytes", call.args[1])

    def test_default_does_not_extract_and_failure_is_safe(self):
        app.dependency_overrides[get_anymize_service] = lambda: SimpleNamespace(anonymize_pdf=AsyncMock(return_value=TEXT))
        extractor = SimpleNamespace(extract=AsyncMock(side_effect=ExtractionError(503, "Property extraction is not configured.")))
        app.dependency_overrides[get_extraction_service] = lambda: extractor
        with TestClient(app) as client:
            upload = {"file": ("property.pdf", b"%PDF-test", "application/pdf")}
            response = client.post("/analyze", files=upload)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("extraction", response.json())
            extractor.extract.assert_not_awaited()
            response = client.post("/analyze?extract_facts=true", files=upload)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(TEXT, response.text)
