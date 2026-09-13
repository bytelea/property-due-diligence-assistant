import unittest
from unittest.mock import AsyncMock
from app.models.property_fact import AnonymizedDocument, DocumentClassification
from app.services.extraction import PropertyFactExtractionService
from app.services.structured_model import ExtractionError
from app.services.extraction_diagnostics import begin, end

class ExtractionDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, output, category=None):
        token = begin(3)
        try:
            with self.assertLogs('app.services.extraction_diagnostics', level='INFO') as logs:
                service = PropertyFactExtractionService(AsyncMock(generate=AsyncMock(return_value=output)))
                doc = AnonymizedDocument(document_id='PRIVATE_ID', text='PRIVATE_TEXT')
                classification = DocumentClassification(document_type='EXPOSE', confidence=1)
                if category:
                    with self.assertRaises(ExtractionError):
                        await service.extract(doc, classification)
                else:
                    self.assertEqual(await service.extract(doc, classification), [])
            text = str(logs.output)
            for forbidden in ('PRIVATE_ID', 'PRIVATE_TEXT', 'PRIVATE_EVIDENCE'):
                self.assertNotIn(forbidden, text)
            if category:
                self.assertIn(category, text)
            self.assertIn("'document_index': 3", text)
            self.assertTrue(all(r.exc_info is None for r in logs.records))
        finally:
            end(token)

    async def test_invalid_json(self):
        await self.check('PRIVATE_TEXT', 'invalid_json')

    async def test_schema_failure(self):
        await self.check('{"facts":"PRIVATE_TEXT"}', 'schema_validation_failed')

    async def test_evidence_failure(self):
        await self.check('{"facts":[{"key":"floor_area","value":92,"unit":"m2","evidence":"PRIVATE_EVIDENCE","confidence":1}]}', 'evidence_validation_failed')

    async def test_empty_result_remains_successful(self):
        await self.check('{"facts":[]}')
