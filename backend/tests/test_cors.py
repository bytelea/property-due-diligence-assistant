import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.cors import configure_cors
from app.main import app as production_app
from app.models.assessment import PropertyAssessment
from app.services.property_analysis import get_property_analysis_service

ORIGIN = "https://propertyscan.lovable.app"


class CorsTests(unittest.TestCase):
    def client(self, environment="production", origins=ORIGIN):
        with patch.dict(os.environ, {"APP_ENV": environment, "ALLOWED_ORIGINS": origins}, clear=True):
            settings = Settings()
        app = FastAPI()
        app.include_router(production_app.router)
        configure_cors(app, settings)
        return TestClient(app)

    def test_production_origin_and_no_credentials(self):
        response = self.client().get('/health', headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], ORIGIN)
        self.assertNotIn('access-control-allow-credentials', response.headers)
        self.assertIn('Origin', response.headers['vary'])

    def test_development_origins(self):
        client = self.client(environment="development", origins="")
        for origin in ('http://localhost:3000', 'http://localhost:5173'):
            response = client.get('/health', headers={'Origin': origin})
            self.assertEqual(response.headers['access-control-allow-origin'], origin)

    def test_unknown_and_lookalike_origins_are_not_allowed(self):
        for origin in ('https://unknown.example', ORIGIN + '.evil.example', 'null', 'http://localhost:3000'):
            response = self.client().get('/health', headers={'Origin': origin})
            self.assertNotIn('access-control-allow-origin', response.headers)

    def test_upload_preflight(self):
        response = self.client().options('/properties/analyze', headers={
            'Origin': ORIGIN, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], ORIGIN)
        self.assertEqual(set(response.headers['access-control-allow-methods'].split(', ')), {'GET', 'POST', 'OPTIONS'})
        self.assertIn('content-type', response.headers['access-control-allow-headers'].lower())

    def test_disallowed_preflight(self):
        for origin, method in [('https://unknown.example', 'POST'), (ORIGIN, 'DELETE')]:
            response = self.client().options('/properties/analyze', headers={
                'Origin': origin, 'Access-Control-Request-Method': method,
            })
            self.assertEqual(response.status_code, 400)
            if origin != ORIGIN:
                self.assertNotIn('access-control-allow-origin', response.headers)

    def test_comma_separated_environment_configuration(self):
        client = self.client(origins=f' {ORIGIN}, https://second.example/ , {ORIGIN}, ')
        for origin in (ORIGIN, 'https://second.example'):
            self.assertEqual(client.get('/health', headers={'Origin': origin}).headers['access-control-allow-origin'], origin)

    def test_production_without_configuration_fails_closed(self):
        self.assertNotIn('access-control-allow-origin', self.client(origins='').get('/health', headers={'Origin': ORIGIN}).headers)

    def test_wildcards_and_invalid_origins_rejected(self):
        for origin in ('*', 'https://*.example', 'https://user:password@example.com', ORIGIN + '/path', ORIGIN + '?query=1'):
            with self.subTest(origin=origin), patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValidationError):
                    Settings(app_env='production', allowed_origins=origin)

    def test_multipart_response_and_validation_unchanged(self):
        client = self.client()
        service = SimpleNamespace(analyze=AsyncMock(return_value=PropertyAssessment(id='synthetic-test')))
        client.app.dependency_overrides[get_property_analysis_service] = lambda: service
        upload = [('files', ('synthetic.pdf', b'%PDF-1.4\nsynthetic', 'application/pdf'))]
        baseline = client.post('/properties/analyze', files=upload)
        response = client.post('/properties/analyze', files=upload, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, baseline.status_code)
        self.assertEqual(response.json(), baseline.json())
        self.assertEqual(response.headers['access-control-allow-origin'], ORIGIN)
        invalid = client.post('/properties/analyze', files=[('files', ('bad.pdf', b'bad', 'application/pdf'))], headers={'Origin': ORIGIN})
        self.assertEqual(invalid.status_code, 200)  # Mock service; validation is now document-isolated.
        self.assertEqual(service.analyze.call_args.args[0][0].validation_error.status_code, 415)
        self.assertEqual(invalid.headers['access-control-allow-origin'], ORIGIN)
        self.assertEqual(service.analyze.await_count, 3)
