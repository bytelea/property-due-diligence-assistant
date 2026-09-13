import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from google.genai import errors

from app.config import Settings
from app.main import app
from app.models.property_fact import DocumentClassification, FactCandidates, PropertyExtraction, PropertyFact
from app.services.anymize import AnymizeError, get_anymize_service
from app.services.extraction import PropertyExtractionService, get_extraction_service
from app.services.property_analysis import get_analysis_engine
from app.services.structured_model import ExtractionError
from tests.synthetic_mvp import synthetic_engine, synthetic_mvp_facts


FIXTURES = synthetic_mvp_facts()
GROUPS = {"listing": [FIXTURES[0], FIXTURES[3]], "plan": [FIXTURES[1]],
          "management": [FIXTURES[2]], "inventory": [FIXTURES[4]]}
PDFS = {name: b"%PDF-1.4\nORIGINAL_SYNTHETIC_" + name.encode() for name in GROUPS}
TEXTS = {name: "\n".join(f.evidence for f in facts) for name, facts in GROUPS.items()}


def doc_id(content):
    return "doc-" + hashlib.sha256(content).hexdigest()


class PropertyAnalysisTests(unittest.TestCase):
    def setUp(self):
        async def anonymize(content):
            name = next(name for name, pdf in PDFS.items() if pdf == content)
            return TEXTS[name]

        async def extract(document):
            name = next(name for name, text in TEXTS.items() if text == document.text)
            facts = [PropertyFact.model_validate({
                **fact.model_dump(exclude_computed_fields=True),
                "document_id": document.document_id,
                "fact_id": document.document_id + ":" + fact.fact_id,
            }) for fact in GROUPS[name]]
            return PropertyExtraction(document_id=document.document_id, classification=DocumentClassification(
                document_type=facts[0].document_type, confidence=1), facts=facts)

        self.anonymizer = SimpleNamespace(anonymize_pdf=AsyncMock(side_effect=anonymize))
        self.extractor = SimpleNamespace(extract=AsyncMock(side_effect=extract))
        self.engine = MagicMock(wraps=synthetic_engine())
        app.dependency_overrides[get_anymize_service] = lambda: self.anonymizer
        app.dependency_overrides[get_extraction_service] = lambda: self.extractor
        app.dependency_overrides[get_analysis_engine] = lambda: self.engine
        self.addCleanup(app.dependency_overrides.clear)

    def upload(self, names=("listing", "plan")):
        with TestClient(app) as client:
            return client.post("/properties/analyze", files=[
                ("files", (name + ".pdf", PDFS[name], "application/pdf")) for name in names
            ])

    def test_two_documents_combined_and_area_conflict(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(len(result["documents"]), 2)
        conflicts = [f for f in result["findings"] if f["type"] == "conflict"]
        self.assertEqual(len(conflicts), 1)
        finding = conflicts[0]
        self.assertEqual(finding["type"], "conflict")
        self.assertEqual(finding["rule_id"], "A19+A30")
        self.assertEqual(len(finding["linked_facts"]), 2)
        sources = {e["document_name"]: e for e in finding["evidence"]}
        for name in ("listing", "plan"):
            self.assertEqual(sources[name + ".pdf"]["document_id"], doc_id(PDFS[name]))
            self.assertEqual(sources[name + ".pdf"]["excerpt"], GROUPS[name][0].evidence)
            self.assertEqual(sources[name + ".pdf"]["page"], 1)
        self.engine.analyze.assert_called_once()
        self.assertEqual(len(self.engine.analyze.call_args.args[0]), 3)
        self.assertEqual(result["processing_status"], "incomplete")
        self.assertTrue(result["run_metadata"]["processing_stages_completed"])
        self.assertEqual(result["decision_readiness"], "NOT_DECISION_READY")
        self.assertNotIn("ORIGINAL_SYNTHETIC", response.text)

    def test_management_cost_and_planning_evidence(self):
        result = self.upload(("listing", "plan", "management", "inventory")).json()
        self.assertEqual({f["type"] for f in result["findings"]}, {"conflict", "documented_fact", "missing_evidence"})
        self.assertEqual(result["known_additional_costs"][0]["amount"], 6500)
        financial = next(f for f in result["findings"] if f["type"] == "documented_fact")
        self.assertEqual(financial["evidence"][0]["document_name"], "management.pdf")
        missing = next(f for f in result["findings"] if f["type"] == "missing_evidence")
        self.assertEqual({e["document_name"] for e in missing["evidence"]}, {"listing.pdf", "inventory.pdf"})
        self.assertIn("unknown", missing["summary"])

    def test_deterministic_combined_output_and_duplicate_documents(self):
        first = self.upload().json()
        second = self.upload(("plan", "listing")).json()
        duplicate = self.upload(("listing", "plan", "listing")).json()
        self.assertEqual(first, second)
        self.assertEqual(first, duplicate)

    def test_identical_content_retains_filename_aliases(self):
        with TestClient(app) as client:
            response = client.post("/properties/analyze", files=[
                ("files", (name, PDFS["listing"], "application/pdf")) for name in ("b.pdf", "a.pdf")
            ])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["documents"][0]["document_names"], ["a.pdf", "b.pdf"])
        self.anonymizer.anonymize_pdf.assert_awaited_once()

    def test_invalid_file_among_uploads_preserves_valid_document(self):
        for filename, content, mime, status in [
            ("bad.txt", b"not pdf", "text/plain", 415),
            ("empty.pdf", b"", "application/pdf", 400),
            ("fake.pdf", b"not pdf", "application/pdf", 415),
            ("wrong.pdf", PDFS["plan"], "text/plain", 415),
        ]:
            with self.subTest(status=status), TestClient(app) as client:
                response = client.post("/properties/analyze", files=[
                    ("files", ("good.pdf", PDFS["listing"], "application/pdf")),
                    ("files", (filename, content, mime)),
                ])
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["technical_processing_completed"])
                self.assertEqual(sorted(d["processing_status"] for d in response.json()["documents"]), ["completed", "failed"])
        self.assertEqual(self.anonymizer.anonymize_pdf.await_count, 4)

    def test_size_count_and_batch_limits(self):
        with patch("app.main.MAX_PDF_BYTES", 5):
            self.assertEqual(self.upload().status_code, 413)
        with patch("app.services.pdf_uploads.MAX_BATCH_BYTES", 5):
            self.assertEqual(self.upload().status_code, 413)
        self.assertEqual(self.upload(tuple(["listing"] * 11)).status_code, 413)
        self.anonymizer.anonymize_pdf.assert_not_awaited()

    def test_missing_or_wrong_file_field(self):
        with TestClient(app) as client:
            self.assertEqual(client.post("/properties/analyze").status_code, 422)
            response = client.post("/properties/analyze", files=[
                ("files", ("a.pdf", PDFS["listing"], "application/pdf")),
                ("file", ("b.pdf", PDFS["plan"], "application/pdf")),
            ])
            self.assertEqual(response.status_code, 400)

    def test_anonymization_failure_preserves_successful_documents(self):
        self.anonymizer.anonymize_pdf.side_effect = [TEXTS["listing"], AnymizeError(502, "SYNTHETIC_PRIVATE_ERROR")]
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", response.text)
        self.engine.analyze.assert_called_once()
        self.assertFalse(response.json()["technical_processing_completed"])

    def test_extraction_failure_does_not_analyze_partial_facts(self):
        self.extractor.extract.side_effect = ExtractionError(503, "SYNTHETIC_PRIVATE_ERROR")
        response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Property extraction provider is unavailable."})
        self.engine.analyze.assert_not_called()

    def test_second_extraction_failure_discards_prior_success(self):
        original = self.extractor.extract.side_effect
        calls = 0

        async def extract(document):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ExtractionError(503, "SYNTHETIC_PRIVATE_ERROR")
            return await original(document)

        self.extractor.extract.side_effect = extract
        with self.assertLogs(level="DEBUG") as logs:
            response = self.upload()
        self.assertEqual(calls, 2)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", response.text + str(logs.output))
        self.assertNotIn("ORIGINAL_SYNTHETIC", response.text + str(logs.output))
        self.engine.analyze.assert_not_called()

    def test_uploads_closed_after_validation_failure(self):
        from io import BytesIO
        from starlette.datastructures import Headers, UploadFile
        from app.main import analyze_property
        import asyncio

        async def check():
            good = UploadFile(BytesIO(PDFS["listing"]), filename="good.pdf", headers=Headers({"content-type": "application/pdf"}))
            bad = UploadFile(BytesIO(b"invalid"), filename="bad.pdf", headers=Headers({"content-type": "application/pdf"}))
            request = SimpleNamespace(form=AsyncMock(return_value=SimpleNamespace(multi_items=lambda: [("files", good), ("files", bad)])))
            service = SimpleNamespace(analyze=AsyncMock())
            from fastapi import HTTPException
            await analyze_property(request, [good, bad], service)
            self.assertTrue(good.file.closed and bad.file.closed)
            service.analyze.assert_awaited_once()
            self.assertTrue(any(d.validation_error is not None for d in service.analyze.call_args.args[0]))

        asyncio.run(check())

    def test_unexpected_failure_is_sanitized(self):
        self.extractor.extract.side_effect = RuntimeError("SYNTHETIC_PRIVATE_ERROR")
        response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", response.text)
        self.engine.analyze.assert_not_called()

    def test_actual_extraction_layer_receives_only_anonymized_text(self):
        async def generate(instruction, content, schema):
            self.assertIn(content, TEXTS.values())
            self.assertNotIn("ORIGINAL_SYNTHETIC", content)
            if schema is DocumentClassification:
                return json.dumps({"document_type": "OTHER", "confidence": 1})
            self.assertIs(schema, FactCandidates)
            return '{"facts": []}'
        model = SimpleNamespace(generate=AsyncMock(side_effect=generate))
        app.dependency_overrides[get_extraction_service] = lambda: PropertyExtractionService(model)
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(model.generate.await_count, 4)
        self.assertEqual(len(response.json()["documents"]), 2)
        self.assertEqual(len(response.json()["run_metadata"]["input_document_ids"]), 2)
        self.assertEqual(response.json()["findings"], [])

    def test_vertex_permission_failure_uses_existing_sanitized_behavior(self):
        app.dependency_overrides[get_extraction_service] = lambda: PropertyExtractionService()
        for code in (401, 403):
            failure = errors.ClientError(code=code, response_json={"error": {"message": "SYNTHETIC_PRIVATE_ERROR"}})
            with patch("app.services.structured_model.get_settings", return_value=Settings(gemini_model="test-model")), patch("app.services.structured_model.genai.Client", side_effect=failure):
                with self.assertLogs("app.services.structured_model", level="WARNING") as logs:
                    response = self.upload()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(logs.records[0].getMessage(), "Vertex AI provider access failed.")
                self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", response.text + str(logs.output))
        self.engine.analyze.assert_not_called()

    def test_mismatched_source_is_rejected(self):
        self.extractor.extract.side_effect = None
        self.extractor.extract.return_value = PropertyExtraction(
            document_id="wrong-document", classification=DocumentClassification(document_type="EXPOSE", confidence=1), facts=[])
        self.assertEqual(self.upload().status_code, 502)
        self.engine.analyze.assert_not_called()

    def test_default_engine_policy_is_unchanged(self):
        del app.dependency_overrides[get_analysis_engine]
        result = self.upload().json()
        self.assertTrue(result["findings"])
        self.assertTrue(all(f["evaluation_status"] == "NEEDS_INPUT" for f in result["findings"]))
        self.assertEqual(result["processing_status"], "incomplete")
        self.assertIsNone(result["run_metadata"]["policy"]["area_absolute_tolerance"])
        self.assertIsNone(result["run_metadata"]["policy"]["max_document_age_days"])
