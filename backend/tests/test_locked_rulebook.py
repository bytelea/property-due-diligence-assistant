"""Scoped workbook regression. Synthetic S01 is NOT Dresden D01-D16."""
from datetime import date
import itertools
import unittest

from pydantic import ValidationError

from app.models.property_fact import PropertyFact
from app.services.analysis_engine import AnalysisEngine
from app.rules.common import money_is_documented
from tests.synthetic_mvp import synthetic_mvp_facts, synthetic_engine


def update(fact, **changes):
    return PropertyFact.model_validate({**fact.model_dump(exclude_computed_fields=True), **changes})


class LockedCanonicalTests(unittest.TestCase):
    def test_canonical_input_and_legacy_output_round_trip(self):
        data = synthetic_mvp_facts()[0].model_dump(exclude_computed_fields=True)
        for old, canonical in (("key", "canonical_key"), ("confidence", "extraction_confidence"),
                               ("document_id", "source_document_id"), ("evidence", "evidence_snippet")):
            data[canonical] = data.pop(old)
        fact = PropertyFact.model_validate(data)
        self.assertEqual(fact.canonical_key, fact.key)
        self.assertEqual(fact.extraction_confidence, fact.confidence)
        self.assertEqual(PropertyFact.model_validate_json(fact.model_dump_json()), fact)

    def test_conflicting_aliases_rejected(self):
        data = synthetic_mvp_facts()[0].model_dump()
        data["canonical_key"] = "different"
        with self.assertRaises(ValidationError):
            PropertyFact.model_validate(data)

    def test_legacy_metadata_is_unknown_not_guessed(self):
        fact = PropertyFact(fact_id="legacy", key="floor_area", value=105, unit="m2",
                            document_id="listing", document_type="EXPOSE", evidence="105 m²", confidence=1)
        self.assertEqual(fact.scope, "unknown")
        self.assertEqual(fact.measurement_type, "unknown")
        self.assertIsNone(fact.entity_id)
        self.assertEqual(synthetic_engine().analyze([fact, synthetic_mvp_facts()[1]]).findings, [])

    def test_distinct_allocation_bases_at03(self):
        fact = synthetic_mvp_facts()[2]
        a = update(fact, allocation_numerator=11.25, allocation_denominator=1000, allocation_basis="title")
        b = update(fact, allocation_numerator=11.25, allocation_denominator=928, allocation_basis="account")
        self.assertNotEqual(a.allocation_denominator, b.allocation_denominator)
        self.assertNotEqual(a.allocation_basis, b.allocation_basis)


class LockedAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.facts = synthetic_mvp_facts()
        self.engine = synthetic_engine()

    def test_s01_comparable_area(self):
        result = self.engine.analyze(self.facts[:2])
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].finding_type, "conflict")

    def test_at07_at08_at14_at21_incompatible_semantics(self):
        left, right = self.facts[:2]
        for changes in [
            {"measurement_type": "tax_area", "value": 44},
            {"measurement_type": "advertised_area"}, {"scope": "building"},
            {"entity_id": "other-unit"}, {"project_id": "other-project"},
            {"factual_date": date(2025, 9, 1)}, {"factual_period": "2025"},
            {"status": "planned"}, {"document_applicability": "not_applicable"},
            {"measurement_type": "unknown"}, {"scope": "unknown"},
            {"amount_type": "actual"},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.engine.analyze([left, update(right, **changes)]).findings, [])

    def test_at22_rounding_and_unconfigured_policy(self):
        a, b = self.facts[:2]
        self.assertEqual(self.engine.analyze([a, update(b, value=104.99)]).findings, [])
        result = AnalysisEngine().analyze(self.facts)
        self.assertEqual(result.findings, [])
        self.assertTrue(any("tolerances" in u for u in result.uncertainties))

    def test_freshness_is_configurable_per_fact_type(self):
        engine = AnalysisEngine(as_of=date(2026, 9, 12), freshness_days_by_key={
            "planned_works_cost": 5, "planning_documentation_reference": 30,
        })
        result = engine.analyze(self.facts)
        self.assertEqual(result.known_additional_costs, [])
        self.assertEqual([f.type for f in result.findings], ["missing_evidence"])

    def test_at04_at05_at13_at14_financial_semantics(self):
        cost = self.facts[2]
        for changes in [
            {"scope": "WEG", "value": 710000, "amount_type": "estimate"},
            {"scope": "project"}, {"scope": "parking"}, {"amount_type": "budget"},
            {"amount_type": "actual", "status": "completed"}, {"amount_type": "reserve"},
            {"frequency": "monthly"}, {"frequency": "annual"}, {"frequency": "unknown"},
            {"project_id": None}, {"entity_id": None}, {"status": "proposed"},
            {"factual_date": date(2023, 1, 1)}, {"document_date": date(2022, 1, 1)},
            {"currency": "USD"}, {"document_applicability": "unknown"},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.engine.analyze([update(cost, **changes)]).known_additional_costs, [])

    def test_known_cost_and_payer_are_separate(self):
        cost = self.engine.analyze([self.facts[2]]).known_additional_costs[0]
        self.assertEqual((cost.amount, cost.scope, cost.amount_type, cost.frequency), (6500, "unit", "contribution", "one-time"))
        self.assertEqual(cost.payer_status, "unknown")

    def test_at01_at10_source_format_and_sign(self):
        base = self.facts[2]
        fact = update(base, raw_value="710.000", number_format="de", value=710000, evidence="EUR 710.000")
        self.assertTrue(money_is_documented(fact))
        self.assertFalse(money_is_documented(update(fact, value=710)))
        self.assertFalse(money_is_documented(update(fact, evidence="EUR -710.000")))
        self.assertTrue(money_is_documented(update(fact, raw_value="1.935,24", value=1935.24, evidence="EUR 1.935,24")))
        self.assertFalse(money_is_documented(update(fact, number_format=None)))
        self.assertEqual(self.engine.analyze([update(base, raw_value=None)]).known_additional_costs, [])

    def test_at06_later_completion_prevents_future_charge(self):
        cost = self.facts[2]
        completion = update(cost, fact_id="completion", status="completed", document_date=date(2026, 9, 10))
        self.assertEqual(self.engine.analyze([cost, completion]).known_additional_costs, [])
        self.assertEqual(cost.status, "approved")

    def test_distinct_projects_not_merged_by_equal_amount(self):
        cost = self.facts[2]
        other = update(cost, fact_id="other-cost", project_id="other-roof")
        self.assertEqual(len(self.engine.analyze([cost, other]).known_additional_costs), 2)
        ambiguous_revision = update(cost, fact_id="revision", value=7200, raw_value="7,200", evidence="Unit contribution EUR 7,200")
        self.assertEqual(self.engine.analyze([cost, ambiguous_revision]).known_additional_costs, [])

    def test_at23_at29_missing_evidence_applicability(self):
        alteration, missing = self.facts[3:]
        good = self.engine.analyze([alteration, missing]).findings[0]
        self.assertEqual(good.type, "missing_evidence")
        self.assertIn("unknown", good.summary)
        self.assertNotIn("illegal", good.summary)
        for changes in [
            {"project_id": "unrelated-extension"}, {"entity_id": "other-unit"},
            {"document_presence": "supplied"}, {"document_presence": "unclear"},
            {"document_presence": "not_applicable"}, {"requirement_applicable": False},
            {"requirement_applicable": None}, {"document_priority": "NICE_TO_HAVE"},
            {"document_applicability": "not_applicable"},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.engine.analyze([alteration, update(missing, **changes)]).findings, [])
        self.assertEqual(self.engine.analyze([alteration]).findings, [])

    def test_at20_at25_traceability_and_uncertainty(self):
        for finding in self.engine.analyze(self.facts).findings:
            self.assertTrue(finding.linked_facts)
            self.assertTrue(finding.rule_id)
            self.assertTrue(finding.rulebook_version)
            self.assertTrue(finding.confidence_reason)
            for evidence in finding.evidence:
                self.assertTrue(evidence.document_id and evidence.page and evidence.evidence_text)
                self.assertIsNotNone(evidence.extraction_confidence)
        for field, value in (("page", None), ("source_authority", "unknown"), ("document_date", None), ("evidence_role", "contextual")):
            self.assertEqual(self.engine.analyze([update(self.facts[0], **{field: value}), self.facts[1]]).findings, [])
        uncertain = update(self.facts[0], confidence=0.2)
        result = self.engine.analyze([uncertain, self.facts[1]])
        self.assertEqual(result.findings[0].severity, "NEEDS_VERIFICATION")
        self.assertEqual(result.findings[0].confidence_label, "Low")

    def test_output_vocabulary_and_determinism(self):
        expected = self.engine.analyze(self.facts).model_dump_json()
        for order in (self.facts, list(reversed(self.facts)), self.facts * 2):
            self.assertEqual(self.engine.analyze(order).model_dump_json(), expected)
        result = self.engine.analyze(self.facts)
        self.assertEqual(result.known_additional_costs, result.financial_impacts)
        self.assertEqual(result.potential_costs, [])
        self.assertEqual(result.run_metadata["model_version"], "none:deterministic")
        self.assertEqual(result.decision_readiness, "NOT_DECISION_READY")


class DresdenScopedRegressionTests(unittest.TestCase):
    """Workbook-summary semantic probes, not original-document extraction fixtures.

    Source dates/page mappings absent from the workbook stay unknown. No 105/92
    or 6500 synthetic amount is inserted into the Dresden regression case.
    """

    def probe(self, case, **fields):
        return PropertyFact(
            fact_id=case + "-probe", canonical_key="planned_works_cost",
            value=fields.pop("value", 0), unit="EUR", currency="EUR",
            document_id="Rulebook:05_Golden_Test_Case:" + case,
            document_type="OTHER", page=None,
            evidence=fields.pop("evidence", "Workbook summary only; original document evidence not loaded."),
            extraction_confidence=1, source_authority="workbook_specification",
            evidence_role="contextual", document_applicability="unknown", **fields,
        )

    def test_d05_project_total_does_not_become_unit_liability(self):
        fact = self.probe("D05", value=710000, entity_id="Dresden-Haus-C", project_id="Dresden-Strangsanierung",
                          scope="project", amount_type="estimate", raw_value="710.000", number_format="de",
                          factual_period="2022", evidence="Haus C total about EUR 710,000; unit allocation not established.")
        self.assertEqual(synthetic_engine().analyze([fact]).financial_impacts, [])
        self.assertEqual(fact.value, 710000)

    def test_d01_separate_asset_identifiers(self):
        assets = [PropertyFact(fact_id="D01-" + entity, canonical_key="asset_identity", value=entity,
                               entity_id=entity, scope=scope, document_id="Rulebook:05:D01",
                               document_type="OTHER", evidence="Workbook asset identity summary.", extraction_confidence=1)
                  for entity, scope in (("Dresden-Wohnung-63", "unit"), ("Dresden-Garage-14", "parking"), ("Dresden-Stellplatz-63", "parking"))]
        self.assertEqual(len({f.entity_id for f in assets}), 3)
        self.assertEqual(synthetic_engine().analyze(assets).findings, [])

    def test_d13_tax_area_not_wohnflaeche(self):
        fact = PropertyFact(fact_id="D13-probe", canonical_key="floor_area", value=44, unit="m2",
                            measurement_type="tax_area", scope="parcel", entity_id="Dresden-tax-input",
                            document_id="Rulebook:05_Golden_Test_Case:D13", document_type="PROPERTY_TAX_DOCUMENT",
                            evidence="Tax calculation uses 44 m² land-value input.", extraction_confidence=1)
        self.assertEqual(fact.measurement_type, "tax_area")
        self.assertEqual(synthetic_engine().analyze([fact]).findings, [])

    def test_d01_d09_d10_assets_and_budget_do_not_become_unit_debt(self):
        probes = [self.probe("D09", entity_id="Dresden-TG", scope="parking", value=284607.36, amount_type="budget", status="approved"),
                  self.probe("D10", entity_id="Dresden-WEG", scope="WEG", value="No unit allocation supplied", amount_type="budget", status="planned")]
        self.assertNotEqual(probes[0].entity_id, probes[1].entity_id)
        self.assertEqual(synthetic_engine().analyze(probes).financial_impacts, [])

    def test_d07_d11_d16_potential_actual_and_historical_not_known_future(self):
        probes = [self.probe("D07", value="2500–3200", amount_type="estimate", factual_period="2023"),
                  self.probe("D11", value="Historical settlement; amount not normalized here", amount_type="actual", status="completed", factual_period="2022"),
                  self.probe("D16", value="Current completion unknown", status="ongoing", factual_period="2022/2023")]
        self.assertEqual(synthetic_engine().analyze(probes).financial_impacts, [])
        self.assertTrue(any("current status" in u for u in synthetic_engine().analyze(probes).uncertainties))
