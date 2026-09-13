import unittest
from pydantic import ValidationError
from app.models.assessment import PropertyAssessment
from app.services.analysis_engine import AnalysisEngine
from app.services.normalization import normalize_facts
from tests.synthetic_mvp import synthetic_mvp_facts, synthetic_engine
from tests.test_canonical_pipeline import change


class VerificationProjectionTests(unittest.TestCase):
    def setUp(self):
        self.facts = normalize_facts(synthetic_mvp_facts())

    def test_incomplete_works_visible_without_liability(self):
        fact = change(self.facts[2], scope='UNKNOWN', entity_id=None, payer_status='UNKNOWN')
        result = AnalysisEngine().analyze([fact])
        finding = result.findings[0]
        self.assertEqual(finding.rule_id, 'B02')
        self.assertEqual(finding.severity, 'NEEDS_VERIFICATION')
        self.assertEqual(finding.evaluation_status, 'NEEDS_INPUT')
        self.assertEqual(finding.scope, 'unknown')
        self.assertIsNone(finding.entity_id)
        self.assertEqual(result.known_additional_costs, [])
        self.assertIsNone(finding.financial_impact)
        self.assertIn('payment', finding.buyer_action)
        evaluation = next(e for e in result.rule_evaluations if e.evaluation_id == finding.rule_evaluation_id)
        self.assertEqual(finding.triggering_fact_ids, evaluation.triggering_fact_ids)
        self.assertEqual(finding.evidence[0].excerpt, fact.evidence)
        self.assertEqual(finding.evidence[0].document_id, fact.document_id)
        self.assertIsNone(evaluation.severity)
        data = result.model_dump()
        data['findings'][0]['severity'] = 'CRITICAL'
        with self.assertRaises(ValidationError):
            PropertyAssessment.model_validate(data)

    def test_generic_projection_and_deterministic_order(self):
        result = AnalysisEngine().analyze(self.facts)
        self.assertTrue({'B02', 'A19+A30', 'B35'}.issubset({f.rule_id for f in result.findings}))
        self.assertEqual(result.model_dump_json(), AnalysisEngine().analyze(list(reversed(self.facts))).model_dump_json())
        for finding in result.findings:
            self.assertTrue(finding.evidence)
            self.assertTrue(finding.buyer_action)

    def test_not_applicable_and_pass_produce_no_warning(self):
        self.assertEqual(AnalysisEngine().analyze([]).findings, [])
        paid = change(self.facts[2], payment_status='paid')
        result = synthetic_engine().analyze([paid])
        self.assertEqual(result.findings, [])

    def test_triggered_findings_not_duplicated(self):
        result = synthetic_engine().analyze(self.facts)
        self.assertEqual(len(result.findings), 3)
        self.assertEqual(len({f.rule_evaluation_id for f in result.findings}), 3)
