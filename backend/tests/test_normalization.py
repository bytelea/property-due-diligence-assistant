"""Phase 1 schema/normalization tests; no provider calls or new property rules."""
import unittest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.main import app
from app.models.assessment import Finding, FinancialImpact, PropertyAssessment
from app.models.canonical import Scope, MeasurementType, AmountType, Payer
from app.models.property_fact import PropertyFact, CanonicalPropertyFact
from app.services.normalization import normalize_fact, normalize_facts, NormalizationError
from tests.synthetic_mvp import synthetic_mvp_facts, synthetic_engine


def fact(**fields):
    data = dict(fact_id="test", canonical_key="floor_area", value=92, unit="m2",
                source_document_id="test-document", document_type="FLOOR_PLAN",
                evidence_snippet="Synthetic area 92 m².", extraction_confidence=0.9)
    data.update(fields)
    return PropertyFact.model_validate(data)


class NormalizationTests(unittest.TestCase):
    def test_legacy_enums_and_canonical_roundtrip(self):
        source = synthetic_mvp_facts()[2]
        normalized = normalize_fact(source)
        self.assertIsInstance(normalized, CanonicalPropertyFact)
        self.assertEqual((normalized.scope, normalized.status, normalized.amount_type,
                          normalized.frequency, normalized.evidence_role),
                         ("UNIT", "APPROVED", "CONTRIBUTION", "ONE_TIME", "SUPPORTS"))
        self.assertEqual(CanonicalPropertyFact.model_validate_json(normalized.model_dump_json()), normalized)
        self.assertEqual(source.scope, "unit")

    def test_scope_is_preserved_without_allocation(self):
        for legacy, canonical in [("unit", "UNIT"), ("project", "PROJECT"), ("WEG", "OWNERS_ASSOCIATION"),
                                  ("parking", "PARKING"), ("storage", "STORAGE"), ("parcel", "PARCEL")]:
            with self.subTest(scope=legacy):
                result = normalize_fact(fact(scope=legacy, value=6500, currency="EUR", entity_id="asset", project_id="project"))
                self.assertEqual(result.scope, canonical)
                self.assertEqual(result.value, 6500)
                self.assertEqual((result.entity_id, result.project_id), ("asset", "project"))
        for scope in Scope:
            self.assertEqual(normalize_fact(fact(scope=scope)).scope, scope)

    def test_measurement_types_and_unit_aliases_do_not_change_meaning(self):
        for measurement in MeasurementType:
            result = normalize_fact(fact(measurement_type=measurement, unit="m²"))
            self.assertEqual(result.measurement_type, measurement)
            self.assertEqual(result.unit, "m2")
        self.assertEqual(normalize_fact(fact(measurement_type="tax_area")).measurement_type, "TAX_AREA")

    def test_unknown_payer_stays_unknown(self):
        result = normalize_fact(fact(scope="unit", currency="EUR", value=6500))
        self.assertEqual(result.payer_status, Payer.UNKNOWN)
        for payer in Payer:
            self.assertEqual(normalize_fact(fact(payer_status=payer)).payer_status, payer)

    def test_ambiguous_legacy_semantics_fail_without_leaking_evidence(self):
        for field, value in [("amount_type", "reserve"), ("amount_type", "balance"), ("payer_status", "unit_owner")]:
            with self.subTest(field=field, value=value):
                source = fact(**{field: value}, evidence_snippet="Synthetic private marker")
                with self.assertRaises(NormalizationError) as error:
                    normalize_fact(source)
                self.assertNotIn("Synthetic private marker", str(error.exception))
                self.assertEqual(getattr(source, field), value)

    def test_planned_actual_and_frequency_remain_distinct(self):
        planned = normalize_fact(fact(status="planned", amount_type="budget", frequency="one-time"))
        actual = normalize_fact(fact(status="completed", amount_type="actual", frequency="monthly"))
        self.assertEqual((planned.status, planned.amount_type, planned.frequency), ("PLANNED", "BUDGET", "ONE_TIME"))
        self.assertEqual((actual.status, actual.amount_type, actual.frequency), ("COMPLETED", "ACTUAL", "MONTHLY"))
        self.assertEqual(normalize_fact(fact(frequency="QUARTERLY")).frequency, "QUARTERLY")
        for amount in AmountType:
            self.assertEqual(normalize_fact(fact(amount_type=amount)).amount_type, amount)

    def test_unknown_dates_authority_and_identity_not_fabricated(self):
        result = normalize_fact(fact())
        for name in ["factual_date", "factual_period", "period_start", "period_end", "document_date",
                     "current_status_date", "entity_id", "project_id", "page", "document_presence"]:
            self.assertIsNone(getattr(result, name))
        self.assertEqual(result.source_authority, "unknown")
        self.assertEqual(result.measurement_type, "UNKNOWN")

    def test_dates_periods_allocation_and_evidence_preserved(self):
        source = fact(period_start="2022-01-01", period_end="2022-12-31", factual_period="2022",
                      document_date="2023-05-01", current_status_date="2023-02-01", factual_date="2022-12-31",
                      allocation_numerator=11.25, allocation_denominator=928, allocation_basis="accounting",
                      source_authority="supplied-label", page=2)
        result = normalize_fact(source)
        for name in ["period_start", "period_end", "factual_period", "document_date", "current_status_date",
                     "factual_date", "allocation_numerator", "allocation_denominator", "allocation_basis",
                     "source_authority", "page", "evidence", "fact_id", "document_id", "confidence"]:
            self.assertEqual(getattr(result, name), getattr(source, name))
        with self.assertRaises(ValidationError):
            fact(period_start="2023-01-01", period_end="2022-01-01")

    def test_money_requires_explicit_locale_and_preserves_sign_and_scope(self):
        source = fact(value="-1.935,24", unit="EUR", number_format="de", scope="project")
        result = normalize_fact(source)
        self.assertEqual((result.value, result.raw_value, result.currency, result.scope),
                         (-1935.24, "-1.935,24", "EUR", "PROJECT"))
        self.assertEqual(normalize_fact(fact(value="1.935", unit="EUR")).value, "1.935")
        with self.assertRaises(NormalizationError):
            normalize_fact(fact(value="1,23,4", unit="EUR", number_format="en"))

    def test_normalization_idempotent_and_does_not_mutate(self):
        sources = synthetic_mvp_facts()
        before = [f.model_dump_json() for f in sources]
        normalized = normalize_facts(sources)
        self.assertEqual(normalize_facts(normalized), normalized)
        self.assertEqual([f.model_dump_json() for f in sources], before)
        self.assertEqual([f.fact_id for f in normalized], [f.fact_id for f in sources])

    def test_new_catalog_states_do_not_infer_findings(self):
        result = normalize_fact(fact(layout_status="DIFFERS", claim_verification_status="UNSUPPORTED_CLAIM",
                                     planning_evidence_status="MISSING", condition_evidence_type="RECOMMENDATION"))
        self.assertEqual(result.planning_evidence_status, "MISSING")
        self.assertEqual(result.condition_evidence_type, "RECOMMENDATION")
        self.assertIsNone(result.document_presence)
        self.assertIsNone(result.requirement_applicable)


class ContractCompatibilityTests(unittest.TestCase):
    def test_existing_api_contract_values_remain_legacy(self):
        client = TestClient(app)
        self.assertEqual(client.get('/health').status_code, 200)
        response = client.get('/demo-assessment')
        self.assertEqual(response.status_code, 200)
        for finding in response.json()['findings']:
            self.assertEqual(finding['id'], finding['finding_id'])
            self.assertEqual(finding['type'], finding['finding_type'])
            self.assertEqual(finding['facts_used'], finding['linked_facts'])
            self.assertEqual(finding['triggering_fact_ids'], finding['linked_facts'])
            self.assertIsInstance(finding['confidence'], (int, float))
            self.assertTrue(finding['type'].islower())

    def test_result_vocabulary_validation_is_not_rule_execution(self):
        base = synthetic_engine().analyze(synthetic_mvp_facts()).findings[0].model_dump(exclude_computed_fields=True)
        base.update(rule_id="B35", rule_result="EVIDENCE_MISSING", evaluation_status="EVALUATED",
                    threshold_reason="Synthetic schema example", playback_template_id="test-only",
                    source_validation_status="PROVISIONAL_POLICY")
        result = Finding.model_validate(base)
        self.assertEqual(result.rule_result, "EVIDENCE_MISSING")
        for changes in [dict(rule_result="illegal"), dict(rule_id="B33")]:
            with self.assertRaises(ValidationError):
                Finding.model_validate({**base, **changes})

    def test_trigger_alias_conflicts_rejected(self):
        base = synthetic_engine().analyze(synthetic_mvp_facts()).findings[0].model_dump(exclude_computed_fields=True)
        with self.assertRaises(ValidationError):
            Finding.model_validate({**base, 'triggering_fact_ids': ['different']})

    def test_known_and_possible_amounts_can_coexist(self):
        base = synthetic_engine().analyze(synthetic_mvp_facts()).findings[0].model_dump(exclude_computed_fields=True)
        known = FinancialImpact(finding_id=base['id'], amount=6500, status='known', description='Synthetic contribution')
        possible = FinancialImpact(finding_id=base['id'], amount=100, status='estimated', description='Synthetic scenario')
        result = Finding.model_validate({**base, 'known_financial_impacts': [known], 'possible_financial_impacts': [possible]})
        self.assertEqual(result.known_financial_impacts[0].amount, 6500)
        self.assertEqual(result.possible_financial_impacts[0].amount, 100)

    def test_processing_completion_does_not_imply_readiness(self):
        result = PropertyAssessment(id='test', technical_processing_completed=True)
        self.assertTrue(result.technical_processing_completed)
        self.assertEqual(result.decision_readiness, 'NOT_DECISION_READY')
        self.assertIsNone(result.processing_status)
