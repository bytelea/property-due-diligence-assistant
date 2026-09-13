"""Canonical production and evaluation regressions; all providers are mocked."""
from datetime import date
import unittest
from unittest.mock import patch
from pydantic import ValidationError

from app.models.assessment import PropertyAssessment
from app.models.property_fact import CanonicalPropertyFact, PropertyFact
from app.models.rule_evaluation import RuleEvaluation
from app.services.analysis_engine import AnalysisEngine
from app.services.normalization import normalize_facts, NormalizationError
from app.services.canonical_analysis import analyze_canonical
from tests.synthetic_mvp import synthetic_engine, synthetic_mvp_facts
from tests import test_property_analysis as pipeline


def change(fact, **values):
    return CanonicalPropertyFact.model_validate({**fact.model_dump(exclude_computed_fields=True), **values})


class CanonicalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.facts = normalize_facts(synthetic_mvp_facts())
        self.engine = synthetic_engine()

    def result(self, facts):
        return self.engine.analyze(facts)

    def evaluation(self, facts, rule):
        return next(e for e in self.result(facts).rule_evaluations if e.rule_id == rule)

    def test_four_states_are_distinct(self):
        absent = self.evaluation([], "A19+A30")
        missing = self.evaluation(self.facts[:1], "A19+A30")
        passed = self.evaluation([self.facts[0], change(self.facts[1], value=105)], "A19+A30")
        triggered = self.evaluation(self.facts[:2], "A19+A30")
        self.assertEqual([e.evaluation_status for e in [absent, missing, passed, triggered]],
                         ["NOT_APPLICABLE", "MISSING_INPUTS", "EVALUATED_PASS", "TRIGGERED"])
        self.assertEqual(missing.workbook_evaluation_status, "NEEDS_INPUT")
        self.assertEqual(passed.workbook_evaluation_status, "EVALUATED")
        self.assertFalse(absent.applicable)

    def test_unconfigured_policy_explicitly_blocks_evaluation(self):
        assessment = AnalysisEngine().analyze(self.facts)
        self.assertTrue(assessment.findings)
        self.assertTrue(all(f.severity == "NEEDS_VERIFICATION" for f in assessment.findings))
        self.assertEqual(assessment.rule_evaluation_completeness, "incomplete")
        missing = {m for e in assessment.rule_evaluations for m in e.missing_inputs}
        self.assertIn("policy.area_absolute_tolerance", missing)
        self.assertIn("policy.as_of", missing)

    def test_tax_area_is_not_living_area_conflict(self):
        result = self.result([self.facts[0], change(self.facts[1], measurement_type="TAX_AREA", value=44)])
        self.assertEqual(result.findings, [])
        self.assertEqual(result.rule_evaluations[0].evaluation_status, "NOT_APPLICABLE")

    def test_unknown_metadata_is_preserved(self):
        bare = PropertyFact(fact_id="bare", key="floor_area", value=92, unit="m2", document_id="doc",
                            document_type="FLOOR_PLAN", evidence="Synthetic 92 m²", confidence=1)
        result = self.result(normalize_facts([bare]))
        f = result.canonical_facts[0]
        self.assertEqual(f.scope, "UNKNOWN")
        self.assertEqual(f.source_authority, "unknown")
        self.assertIsNone(f.page)
        self.assertIsNone(f.document_date)
        self.assertEqual(result.rule_evaluation_completeness, "incomplete")

    def test_unknown_payer_is_not_buyer_liability(self):
        result = self.result([self.facts[2]])
        self.assertEqual(result.known_additional_costs[0].amount, 6500)
        self.assertEqual(result.known_additional_costs[0].payer_status, "unknown")
        evaluation = next(e for e in result.rule_evaluations if e.rule_id == "B02")
        self.assertFalse(evaluation.calculation_inputs['buyer_liability_assumed'])
        self.assertEqual(result.canonical_facts[0].payer_status, "UNKNOWN")

    def test_project_total_requires_allocation_not_unit_cost(self):
        for scope in ["PROJECT", "OWNERS_ASSOCIATION"]:
            result = self.result([change(self.facts[2], scope=scope)])
            self.assertEqual(result.known_additional_costs, [])
            evaluation = next(e for e in result.rule_evaluations if e.rule_id == "B02")
            self.assertEqual(evaluation.evaluation_status, "MISSING_INPUTS")
            self.assertIn("explicit_unit_allocation", evaluation.missing_inputs)

    def test_completed_work_is_not_payment(self):
        completed = change(self.facts[2], status="COMPLETED")
        evaluation = self.evaluation([completed], "B02")
        self.assertEqual(evaluation.evaluation_status, "MISSING_INPUTS")
        self.assertIn("current_outstanding_payment_evidence", evaluation.missing_inputs)
        outstanding = change(completed, payment_status="unpaid", current_status_date=date(2026, 9, 10))
        result = self.result([outstanding])
        self.assertEqual(result.known_additional_costs[0].amount, 6500)
        self.assertEqual(result.canonical_facts[0].status, "COMPLETED")

    def test_old_due_date_does_not_imply_settlement(self):
        overdue = change(self.facts[2], factual_date=date(2026, 8, 1))
        self.assertEqual(self.evaluation([overdue], "B02").evaluation_status, "MISSING_INPUTS")
        outstanding = change(overdue, payment_status="unpaid", current_status_date=date(2026, 9, 10))
        self.assertEqual(self.result([outstanding]).known_additional_costs[0].amount, 6500)
        paid = change(overdue, payment_status="paid")
        self.assertEqual(self.evaluation([paid], "B02").evaluation_status, "EVALUATED_PASS")
        self.assertEqual(self.result([paid]).known_additional_costs, [])

    def test_other_project_payment_does_not_settle_unit_contribution(self):
        other = change(self.facts[2], fact_id="different-payment", factual_date=date(2026, 9, 1), payment_status="paid")
        self.assertEqual(len(self.result([self.facts[2], other]).known_additional_costs), 1)

    def test_historical_actual_and_recurring_are_not_upcoming_contributions(self):
        for fields in [dict(amount_type="ACTUAL", status="COMPLETED"), dict(frequency="MONTHLY")]:
            result = self.result([change(self.facts[2], **fields)])
            self.assertEqual(result.known_additional_costs, [])
            self.assertEqual(next(e for e in result.rule_evaluations if e.rule_id == "B02").evaluation_status, "NOT_APPLICABLE")

    def test_planning_silence_is_missing_input_not_illegality(self):
        result = self.result([self.facts[3]])
        self.assertEqual(result.findings[0].severity, "NEEDS_VERIFICATION")
        self.assertEqual(self.evaluation([self.facts[3]], "B35").evaluation_status, "MISSING_INPUTS")
        finding = self.result(self.facts[3:]).findings[0]
        self.assertEqual(finding.rule_result, "EVIDENCE_MISSING")
        self.assertEqual(finding.type, "missing_evidence")
        self.assertIn("unknown", finding.summary)
        self.assertIn("does not establish non-compliance", finding.summary)

    def test_trace_chain_and_tampered_evidence_rejected(self):
        result = self.result(self.facts)
        evaluations = {e.evaluation_id: e for e in result.rule_evaluations}
        facts = {f.fact_id: f for f in result.canonical_facts}
        for finding in result.findings:
            evaluation = evaluations[finding.rule_evaluation_id]
            self.assertEqual(finding.triggering_fact_ids, evaluation.facts_used)
            self.assertEqual(finding.rule_id, evaluation.rule_id)
            for evidence in finding.evidence:
                fact = facts[evidence.fact_id]
                self.assertEqual((evidence.document_id, evidence.page, evidence.excerpt), (fact.document_id, fact.page, fact.evidence))
        data = result.model_dump()
        data['findings'][0]['evidence'][0]['excerpt'] = 'different evidence'
        with self.assertRaises(ValidationError):
            PropertyAssessment.model_validate(data)

    def test_order_and_duplicates_are_deterministic(self):
        expected = self.result(self.facts).model_dump_json()
        self.assertEqual(expected, self.result(list(reversed(self.facts))).model_dump_json())
        self.assertEqual(expected, self.result(self.facts * 2).model_dump_json())

    def test_canonical_engine_never_invokes_legacy_rules(self):
        with patch('app.rules.floor_area.evaluate', side_effect=AssertionError('legacy')), \
             patch('app.rules.planned_works.evaluate', side_effect=AssertionError('legacy')), \
             patch('app.rules.planning_documents.evaluate', side_effect=AssertionError('legacy')):
            self.assertEqual(len(self.result(self.facts).findings), 3)
        with self.assertRaises(ValueError):
            analyze_canonical(synthetic_mvp_facts(), self.engine.policy)

    def test_invalid_evaluation_state_rejected(self):
        evaluation = self.evaluation(self.facts[:2], "A19+A30")
        self.assertEqual(RuleEvaluation.model_validate_json(evaluation.model_dump_json()), evaluation)
        with self.assertRaises(ValidationError):
            RuleEvaluation.model_validate({**evaluation.model_dump(), 'evaluation_status': 'MISSING_INPUTS'})


class ProductionCanonicalTests(unittest.TestCase):
    setUp = pipeline.PropertyAnalysisTests.setUp
    upload = pipeline.PropertyAnalysisTests.upload

    def test_real_pipeline_normalizes_before_engine(self):
        with patch('app.services.property_analysis.normalize_facts', wraps=normalize_facts) as normalize:
            result = self.upload()
        self.assertEqual(result.status_code, 200)
        normalize.assert_called_once()
        self.assertTrue(all(isinstance(f, CanonicalPropertyFact) for f in self.engine.analyze.call_args.args[0]))
        self.assertTrue(all(f.scope == "UNIT" for f in self.engine.analyze.call_args.args[0]))
        data = result.json()
        self.assertTrue(data['technical_processing_completed'])
        self.assertEqual(data['decision_readiness'], 'NOT_DECISION_READY')
        self.assertEqual(data['rule_evaluation_completeness'], 'incomplete')  # alteration lacks inventory
        self.assertNotIn('ORIGINAL_SYNTHETIC', result.text)

    def test_normalization_failure_sanitized_no_partial_assessment(self):
        with patch('app.services.property_analysis.normalize_facts', side_effect=NormalizationError('SYNTHETIC_PRIVATE_MARKER')):
            response = self.upload()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', response.text)
        self.assertIn('normalization failed', response.text)
        self.engine.analyze.assert_not_called()

    def test_full_production_trace_and_existing_fields(self):
        response = self.upload(('listing', 'plan', 'management', 'inventory'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['rule_evaluation_completeness'], 'complete')
        facts = {f['fact_id']: f for f in data['canonical_facts']}
        evaluations = {e['evaluation_id']: e for e in data['rule_evaluations']}
        for finding in data['findings']:
            self.assertEqual(finding['type'], finding['finding_type'])
            self.assertEqual(finding['linked_facts'], finding['triggering_fact_ids'])
            self.assertEqual(finding['resolution_status'], 'UNRESOLVED')
            self.assertEqual(finding['triggering_fact_ids'], evaluations[finding['rule_evaluation_id']]['facts_used'])
            for evidence in finding['evidence']:
                self.assertEqual(evidence['document_id'], facts[evidence['fact_id']]['source_document_id'])
                self.assertTrue(evidence['document_name'])
        self.assertEqual(data, self.upload(('inventory', 'management', 'plan', 'listing')).json())
