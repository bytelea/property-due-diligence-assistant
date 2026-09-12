import unittest

from fastapi.testclient import TestClient

from app.main import app


class ApiSmokeTests(unittest.TestCase):
    def test_health(self):
        with TestClient(app) as client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ok",
            "service": "property-due-diligence-assistant",
        })

    def test_demo_assessment(self):
        with TestClient(app) as client:
            response = client.get("/demo-assessment")
        self.assertEqual(response.status_code, 200)
        assessment = response.json()
        self.assertTrue(assessment["is_demo"])
        self.assertEqual(len(assessment["findings"]), 3)
        findings = {finding["id"]: finding for finding in assessment["findings"]}
        area = findings["floor-area-conflict"]
        self.assertIn("105 m²", area["evidence"][0]["excerpt"])
        self.assertIn("92 m²", area["evidence"][1]["excerpt"])
        self.assertEqual(findings["missing-planning-documentation"]["type"], "missing_evidence")
        for finding in findings.values():
            self.assertTrue(finding["evidence"])
            self.assertTrue(finding["buyer_action"])
        impact = assessment["financial_impacts"][0]
        self.assertEqual(impact["finding_id"], "upcoming-works")
        self.assertEqual(impact["amount"], 6500)
        self.assertEqual(impact["currency"], "EUR")
        self.assertEqual(impact["status"], "known")
