import itertools
import unittest
from unittest.mock import patch

from app.models.property_fact import PropertyFact
from app.services.analysis_engine import AnalysisEngine
from tests.synthetic_mvp import synthetic_mvp_facts, synthetic_engine


def changed(fact, **updates):
    return PropertyFact.model_validate({**fact.model_dump(exclude_computed_fields=True), **updates})


class AnalysisEngineTests(unittest.TestCase):
    def setUp(self):
        self.facts = synthetic_mvp_facts()
        self.engine = synthetic_engine()

    def test_synthetic_mvp_all_findings_and_linked_evidence(self):
        assessment = self.engine.analyze(self.facts)
        self.assertEqual(len(assessment.findings), 3)
        self.assertEqual({f.type for f in assessment.findings}, {"conflict", "documented_fact", "missing_evidence"})
        lookup = {f.fact_id: f for f in self.facts}
        for finding in assessment.findings:
            self.assertTrue(finding.buyer_action)
            for evidence in finding.evidence:
                fact = lookup[evidence.fact_id]
                self.assertEqual(evidence.excerpt, fact.evidence)
                self.assertEqual(evidence.document_id, fact.document_id)
                self.assertEqual(evidence.document_type, fact.document_type.value)
                self.assertEqual(evidence.page, fact.page)
        area = next(f for f in assessment.findings if f.type == "conflict")
        self.assertEqual({e.fact_id for e in area.evidence}, {"area-listing", "area-plan"})
        self.assertIn("105 m²", area.summary)
        self.assertIn("92 m²", area.summary)
        self.assertEqual(len(assessment.financial_impacts), 1)
        impact = assessment.financial_impacts[0]
        self.assertEqual((impact.amount, impact.currency, impact.status), (6500, "EUR", "known"))
        self.assertIn(impact.finding_id, {f.id for f in assessment.findings})

    def test_planning_is_unknown_not_noncompliance(self):
        finding = next(f for f in self.engine.analyze(self.facts).findings if f.category == "planning")
        self.assertIn("unknown", finding.summary)
        self.assertIn("does not establish non-compliance", finding.summary)
        self.assertNotIn("illegal", finding.model_dump_json())
        self.assertIn("Request", finding.buyer_action)

    def test_empty_or_incomplete_trigger_sets(self):
        self.assertEqual(self.engine.analyze([]).findings, [])
        self.assertEqual(self.engine.analyze([]).financial_impacts, [])
        for index in (0, 1, 3, 4):
            self.assertEqual(self.engine.analyze([self.facts[index]]).findings, [])
        without_cost = self.engine.analyze([f for f in self.facts if f.key != "planned_works_cost"])
        self.assertEqual(without_cost.financial_impacts, [])

    def test_area_rule_compares_values_not_golden_constants(self):
        pair = [changed(self.facts[0], value=120, evidence="Floor area: 120 m²."),
                changed(self.facts[1], value=100, evidence="Floor area: 100 m².")]
        self.assertEqual(len(self.engine.analyze(pair).findings), 1)
        for value in (120, 119, 118):
            pair[1] = changed(pair[1], value=value, evidence=f"Floor area: {value} m².")
            self.assertEqual(self.engine.analyze(pair).findings, [])

    def test_area_documents_and_measurement_bases(self):
        left, right = self.facts[:2]
        for modified in [changed(right, document_id=left.document_id), changed(right, document_applicability="not_applicable")]:
            self.assertEqual(self.engine.analyze([left, modified]).findings, [])
        left = changed(left, evidence="Living area: 105 m².", measurement_type="living_area")
        right = changed(right, evidence="Usable area: 92 m².", measurement_type="usable_area")
        self.assertEqual(self.engine.analyze([left, right]).findings, [])

    def test_undocumented_estimated_unallocated_or_paid_costs_not_known(self):
        cost = self.facts[2]
        for updates in [
            {"source_authority": "unknown"}, {"amount_type": "estimate"},
            {"scope": "WEG"}, {"amount_type": "actual", "status": "completed"},
            {"payment_status": "paid"}, {"status": "cancelled"},
        ]:
            with self.subTest(updates=updates):
                assessment = self.engine.analyze([changed(cost, **updates)])
                self.assertEqual(assessment.financial_impacts, [])
                self.assertEqual(assessment.findings, [])

    def test_other_documented_amount_and_german_evidence(self):
        cost = changed(self.facts[2], value=7200, evidence="Geplante Dacharbeiten: Anteil dieser Wohnung 7.200 EUR.", raw_value="7.200", number_format="de")
        self.assertEqual(self.engine.analyze([cost]).financial_impacts[0].amount, 7200)

    def test_missing_planning_requires_explicit_absence_and_existing_extension(self):
        extension, missing = self.facts[3:]
        vague = changed(missing, value="Planning documents discussed.", evidence="Planning documents discussed.", document_presence="unclear")
        self.assertEqual(self.engine.analyze([extension, vague]).findings, [])
        for text in ("No extension exists.", "A rear extension is proposed."):
            self.assertEqual(self.engine.analyze([changed(extension, value=text, evidence=text, status="proposed"), missing]).findings, [])
        supplied = changed(missing, fact_id="supplied", value="Planning permission was supplied.", evidence="Planning permission was supplied.", document_presence="supplied")
        self.assertEqual(self.engine.analyze([extension, missing, supplied]).findings, [])

    def test_order_independence_repetition_and_no_input_mutation(self):
        original = [f.model_dump() for f in self.facts]
        expected = self.engine.analyze(self.facts).model_dump_json()
        for permutation in itertools.permutations(self.facts):
            self.assertEqual(self.engine.analyze(list(permutation)).model_dump_json(), expected)
        self.assertEqual(self.engine.analyze(self.facts * 2).model_dump_json(), expected)
        self.assertEqual([f.model_dump() for f in self.facts], original)

    def test_repeated_cost_not_double_counted(self):
        cost = self.facts[2]
        duplicate = changed(cost, fact_id="works-copy", document_id="minutes-copy")
        assessment = self.engine.analyze([cost, duplicate])
        self.assertEqual(len(assessment.financial_impacts), 1)
        self.assertEqual(len(assessment.findings[0].evidence), 2)

    def test_conflicting_identifiers_and_invalid_thresholds_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.analyze([self.facts[0], changed(self.facts[0], value=110)])
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                AnalysisEngine(area_absolute_tolerance=value)

    def test_no_external_clients_are_used(self):
        with patch("socket.socket", side_effect=AssertionError("Network access prohibited")), patch("google.genai.Client", side_effect=AssertionError("Model access prohibited")):
            self.assertEqual(len(self.engine.analyze(self.facts).findings), 3)
