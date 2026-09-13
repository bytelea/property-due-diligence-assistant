import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.main import app
from app.services.property_analysis import PropertyAnalysisService, get_property_analysis_service
from app.services.analysis_engine import AnalysisEngine
from app.services.structured_model import ExtractionError
from app.models.property_fact import PropertyExtraction, PropertyFact, DocumentClassification

class PartialAnalysisTests(unittest.TestCase):
    def run_batch(self, failures=(), repair=False, global_error=False):
        attempts = Counter()
        async def anonymize(content):
            return 'Anonymized area 92 m2 doc ' + content.decode().split()[-1]
        async def extract(document):
            index = int(document.text.split()[-1])
            attempts[index] += 1
            if index in failures and (not repair or attempts[index] == 1):
                raise ExtractionError(503 if global_error else 502, 'sanitized test failure')
            fact = PropertyFact(fact_id='fact-' + str(index), document_id=document.document_id,
                document_type='FLOOR_PLAN', key='floor_area', value=92, unit='m2', evidence=document.text, confidence=1)
            return PropertyExtraction(document_id=document.document_id,
                classification=DocumentClassification(document_type='FLOOR_PLAN', confidence=1), facts=[fact])
        service = PropertyAnalysisService(SimpleNamespace(anonymize_pdf=anonymize), SimpleNamespace(extract=extract), AnalysisEngine())
        app.dependency_overrides[get_property_analysis_service] = lambda: service
        try:
            with TestClient(app) as client:
                response = client.post('/properties/analyze', files=[('files', (f'{i}.pdf', f'%PDF-1.4 ORIGINAL_PRIVATE {i}'.encode(), 'application/pdf')) for i in range(6)])
        finally:
            app.dependency_overrides.clear()
        self.assertNotIn('ORIGINAL_PRIVATE', response.text)
        return response, attempts

    def test_six_successful(self):
        response, attempts = self.run_batch()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['technical_processing_completed'])
        self.assertEqual(len(response.json()['canonical_facts']), 6)
        self.assertTrue(all(n == 1 for n in attempts.values()))

    def test_five_successful_one_failed_preserves_trace(self):
        response, attempts = self.run_batch({2})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(attempts[2], 2)
        self.assertFalse(data['technical_processing_completed'])
        self.assertEqual(data['processing_status'], 'incomplete')
        self.assertEqual(data['rule_evaluation_completeness'], 'incomplete')
        self.assertEqual(data['decision_readiness'], 'NOT_DECISION_READY')
        failed = [d for d in data['documents'] if d['processing_status'] == 'failed']
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['fact_ids'], [])
        self.assertEqual(len(data['canonical_facts']), 5)
        self.assertNotIn(failed[0]['document_id'], {f['document_id'] for f in data['canonical_facts']})
        for finding in data['findings']:
            for evidence in finding['evidence']:
                self.assertNotEqual(evidence['document_id'], failed[0]['document_id'])
        self.assertTrue(any('could not be fully analyzed' in u for u in data['uncertainties']))
        self.assertTrue(data['findings'])

    def test_repair_succeeds(self):
        response, attempts = self.run_batch({2}, repair=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(attempts[2], 2)
        self.assertTrue(response.json()['technical_processing_completed'])
        self.assertTrue(all(d['processing_status'] == 'completed' for d in response.json()['documents']))

    def test_all_fail_is_sanitized_hard_error(self):
        response, attempts = self.run_batch(set(range(6)))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {'detail':'Document extraction failed; no assessment was completed.'})
        self.assertTrue(all(n == 2 for n in attempts.values()))

    def test_global_access_failure_stays_hard_error(self):
        response, attempts = self.run_batch(set(range(6)), global_error=True)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(sum(attempts.values()), 1)
