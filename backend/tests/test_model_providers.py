"""Provider regression tests use mock transports only; no real credentials or IO."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import app
from app.models.property_fact import AnonymizedDocument, DocumentClassification, FactCandidates
from app.services.anymize import get_anymize_service
from app.services.anymize_model import AnymizeStructuredModel
from app.services.extraction import PropertyExtractionService, get_extraction_service
from app.services.structured_model import ExtractionError, GeminiStructuredModel, get_structured_model

MODEL = 'gemini-2.5-flash'
TEST_SECRET = 'synthetic-test-only-key'
TEXT = 'Floor area 92 m². [[Person-test123]] reported a rear extension.'
FACTS = {'facts': [{'key': 'floor_area', 'value': 92, 'unit': 'm2', 'evidence': 'Floor area 92 m².', 'confidence': 0.9},
                   {'key': 'extension_reference', 'value': '[[Person-test123]] reported a rear extension.', 'unit': None,
                    'evidence': '[[Person-test123]] reported a rear extension.', 'confidence': 0.8}]}
CLASSIFICATION = {'document_type': 'EXPOSE', 'confidence': 0.9}


def settings(provider='anymize', **overrides):
    with patch.dict(os.environ, {}, clear=True):
        return Settings(**{'model_provider': provider, 'anymize_model': MODEL,
                           'anymize_api_key': TEST_SECRET, 'gemini_model': 'synthetic-vertex-model', **overrides})


def envelope(content, **overrides):
    return {'model': MODEL, 'choices': [{'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}], **overrides}


class ProviderSelectionTests(unittest.TestCase):
    def test_default_and_explicit_vertex_selection(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings().model_provider, 'vertex')
        with patch('app.services.structured_model.get_settings', return_value=settings('vertex')):
            self.assertIsInstance(get_structured_model(), GeminiStructuredModel)
            self.assertIsInstance(PropertyExtractionService().extractor.model, GeminiStructuredModel)

    def test_anymize_selection_shared_by_classification_and_extraction(self):
        with patch('app.services.structured_model.get_settings', return_value=settings()):
            service = PropertyExtractionService()
        self.assertIsInstance(service.extractor.model, AnymizeStructuredModel)
        self.assertIs(service.extractor.model, service.classifier.model)

    def test_invalid_provider_is_not_silently_replaced(self):
        with patch.dict(os.environ, {'MODEL_PROVIDER': 'invalid-provider'}, clear=True):
            with self.assertRaises(ValidationError):
                Settings()


class AnymizeModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_endpoint_schema_and_placeholder_preservation(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=envelope(json.dumps(FACTS)))
        adapter = AnymizeStructuredModel(httpx.MockTransport(handle))
        with patch('app.services.anymize_model.get_settings', return_value=settings()):
            result = await adapter.generate('Extract property facts.', TEXT, FactCandidates)
        self.assertEqual(json.loads(result), FACTS)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(str(request.url), 'https://app.anymize.ai/api/v1/llm/chat/completions')
        self.assertEqual(request.headers['authorization'], 'Bearer ' + TEST_SECRET)
        body = json.loads(request.content)
        self.assertEqual(body['model'], MODEL)
        self.assertEqual(body['messages'][1]['content'], TEXT)
        self.assertNotIn(TEST_SECRET, request.content.decode())
        self.assertNotIn('original_text', body)
        self.assertFalse(body['stream'])
        self.assertEqual(body['response_format'], {'type': 'json_schema', 'json_schema': {
            'name': 'FactCandidates', 'schema': FactCandidates.model_json_schema()}})
        self.assertIn('character-for-character', body['messages'][0]['content'])

    async def test_both_providers_produce_same_extraction_schema(self):
        responses = [CLASSIFICATION, FACTS]
        def handle(request):
            body = json.loads(request.content)
            schema = body['response_format']['json_schema']
            expected = DocumentClassification if schema['name'] == 'DocumentClassification' else FactCandidates
            self.assertEqual(schema['schema'], expected.model_json_schema())
            self.assertEqual(body['messages'][1]['content'], TEXT)
            return httpx.Response(200, json=envelope(json.dumps(responses[0 if expected is DocumentClassification else 1])))
        document = AnonymizedDocument(document_id='synthetic-document', text=TEXT)
        with patch('app.services.anymize_model.get_settings', return_value=settings()):
            anymize = await PropertyExtractionService(AnymizeStructuredModel(httpx.MockTransport(handle))).extract(document)
        with patch('app.services.structured_model.get_settings', return_value=settings('vertex')), patch('app.services.structured_model.genai.Client') as factory:
            client = MagicMock()
            client.models.generate_content = AsyncMock(side_effect=[SimpleNamespace(text=json.dumps(r)) for r in responses])
            factory.return_value.aio.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.aio.__aexit__ = AsyncMock(return_value=False)
            vertex = await PropertyExtractionService(GeminiStructuredModel()).extract(document)
            for call, schema in zip(client.models.generate_content.await_args_list, (DocumentClassification, FactCandidates)):
                self.assertEqual(call.kwargs['contents'], TEXT)
                self.assertEqual(call.kwargs['config'].response_json_schema, schema.model_json_schema())
        self.assertEqual(anymize.model_dump(), vertex.model_dump())

    async def test_missing_configuration_never_calls_provider(self):
        def fail(request):
            self.fail('No network call expected')
        for values in ({'anymize_api_key': ''}, {'anymize_model': ''}):
            with patch('app.services.anymize_model.get_settings', return_value=settings(**values)):
                with self.assertRaises(ExtractionError) as caught:
                    await AnymizeStructuredModel(httpx.MockTransport(fail)).generate('instruction', TEXT, FactCandidates)
                self.assertEqual(caught.exception.status_code, 503)

    async def test_unavailable_errors_sanitized_no_fallback(self):
        for status in (401, 403, 404, 429, 500, 503):
            def handle(request):
                return httpx.Response(status, json={'error': TEST_SECRET + TEXT})
            with patch('app.services.anymize_model.get_settings', return_value=settings()), patch('app.services.structured_model.genai.Client') as vertex:
                capture = (self.assertLogs('app.services.anymize_model', level='WARNING') if status in (401, 403)
                           else self.assertNoLogs('app.services.anymize_model', level='WARNING'))
                with capture as logs:
                    with self.assertRaises(ExtractionError) as caught:
                        await AnymizeStructuredModel(httpx.MockTransport(handle)).generate('instruction', TEXT, FactCandidates)
                if status in (401, 403):
                    self.assertEqual([r.getMessage() for r in logs.records], ['Anymize model provider access failed.'])
                    self.assertTrue(all(r.exc_info is None and r.args == () for r in logs.records))
                    self.assertNotIn(TEST_SECRET, str(logs.output))
                    self.assertNotIn(TEXT, str(logs.output))
                self.assertEqual(caught.exception.status_code, 503)
                self.assertNotIn(TEST_SECRET, str(caught.exception))
                self.assertNotIn(TEXT, str(caught.exception))
                vertex.assert_not_called()

    async def test_malformed_truncated_refused_and_invalid_schema_responses(self):
        bad = [[], {}, envelope('not JSON'), envelope('{"facts": "wrong"}'), envelope(json.dumps({'facts': [], 'original_text': TEXT})),
               envelope('{}', choices=[]), envelope('{}', choices=[{'finish_reason': 'length', 'message': {'role': 'assistant', 'content': '{}'}}]),
               envelope('{}', choices=[{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}', 'refusal': 'refused'}}])]
        for payload in bad:
            with patch('app.services.anymize_model.get_settings', return_value=settings()):
                adapter = AnymizeStructuredModel(httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
                with self.assertRaises(ExtractionError) as caught:
                    await adapter.generate('instruction', TEXT, FactCandidates)
                self.assertEqual(caught.exception.status_code, 502)
                self.assertNotIn(TEXT, str(caught.exception))

    async def test_changed_placeholder_and_echoed_secret_are_rejected(self):
        for value in ('[[Person-other]]', TEST_SECRET):
            payload = {'facts': [{**FACTS['facts'][1], 'value': value, 'evidence': value}]}
            with patch('app.services.anymize_model.get_settings', return_value=settings()):
                adapter = AnymizeStructuredModel(httpx.MockTransport(lambda request: httpx.Response(200, json=envelope(json.dumps(payload)))))
                with self.assertRaises(ExtractionError) as caught:
                    await adapter.generate('instruction', TEXT, FactCandidates)
                self.assertEqual(caught.exception.status_code, 502)
                self.assertNotIn(value, str(caught.exception))

    async def test_different_model_is_rejected_not_accepted_as_fallback(self):
        with patch('app.services.anymize_model.get_settings', return_value=settings()):
            adapter = AnymizeStructuredModel(httpx.MockTransport(lambda request: httpx.Response(200, json=envelope('{"facts":[]}', model='different-model'))))
            with self.assertRaises(ExtractionError) as caught:
                await adapter.generate('instruction', TEXT, FactCandidates)
            self.assertEqual(caught.exception.status_code, 503)

    async def test_transport_errors_and_timeouts_sanitized(self):
        for error, status in [(httpx.ReadTimeout(TEST_SECRET + TEXT), 504), (httpx.ConnectError(TEST_SECRET + TEXT), 502)]:
            def handle(request):
                raise error
            with patch('app.services.anymize_model.get_settings', return_value=settings()):
                with self.assertRaises(ExtractionError) as caught:
                    await AnymizeStructuredModel(httpx.MockTransport(handle)).generate('instruction', TEXT, FactCandidates)
                self.assertEqual(caught.exception.status_code, status)
                self.assertNotIn(TEST_SECRET, str(caught.exception))
                self.assertNotIn(TEXT, str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    async def test_redirect_is_not_followed(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(307, headers={'Location': 'https://untrusted.example'})
        with patch('app.services.anymize_model.get_settings', return_value=settings()):
            with self.assertRaises(ExtractionError):
                await AnymizeStructuredModel(httpx.MockTransport(handle)).generate('instruction', TEXT, FactCandidates)
        self.assertEqual(len(calls), 1)


class ProviderRouteTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_both_routes_only_send_anonymized_text_to_selected_provider(self):
        for provider in ('vertex', 'anymize'):
            for path in ('/analyze?extract_facts=true', '/properties/analyze'):
                settings_value = settings(provider)
                captured = []
                def handle(request):
                    body = json.loads(request.content)
                    captured.append(body['messages'][1]['content'])
                    output = CLASSIFICATION if body['response_format']['json_schema']['name'] == 'DocumentClassification' else FACTS
                    return httpx.Response(200, json=envelope(json.dumps(output)))
                anymize = AnymizeStructuredModel(httpx.MockTransport(handle))
                app.dependency_overrides[get_anymize_service] = lambda: SimpleNamespace(anonymize_pdf=AsyncMock(return_value=TEXT))
                app.dependency_overrides[get_extraction_service] = lambda: PropertyExtractionService()
                with patch('app.services.structured_model.get_settings', return_value=settings_value), \
                     patch('app.services.anymize_model.get_settings', return_value=settings_value), \
                     patch('app.services.anymize_model.AnymizeStructuredModel', return_value=anymize), \
                     patch('app.services.structured_model.genai.Client') as vertex:
                    client = MagicMock()
                    client.models.generate_content = AsyncMock(side_effect=[SimpleNamespace(text=json.dumps(v)) for v in (CLASSIFICATION, FACTS)])
                    vertex.return_value.aio.__aenter__ = AsyncMock(return_value=client)
                    vertex.return_value.aio.__aexit__ = AsyncMock(return_value=False)
                    with TestClient(app) as api:
                        response = api.post(path, files=[('files' if path.startswith('/properties') else 'file',
                            ('synthetic.pdf', b'%PDF-1.4 ORIGINAL_PRIVATE_SENTINEL', 'application/pdf'))])
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn('ORIGINAL_PRIVATE_SENTINEL', response.text)
                    self.assertNotIn(TEST_SECRET, response.text)
                    if provider == 'vertex':
                        captured = [call.kwargs['contents'] for call in client.models.generate_content.await_args_list]
                    else:
                        vertex.assert_not_called()
                    self.assertEqual(captured, [TEXT, TEXT])


class ModelDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_categories_and_no_sensitive_metadata(self):
        cases = [(401, {}, 'auth_error', 503), (403, {}, 'auth_error', 503),
                 (404, {}, 'model_not_found', 503), (429, {}, 'rate_limited', 503),
                 (500, {}, 'provider_5xx', 503),
                 (200, envelope('{}', model='other'), 'response_model_mismatch', 503),
                 (200, envelope('not-json'), 'invalid_json', 502),
                 (200, envelope('{"facts":"wrong"}'), 'schema_validation_failed', 502),
                 (200, envelope(''), 'missing_content', 502)]
        for status, payload, category, public_status in cases:
            with self.subTest(category=category):
                payload['private_metadata'] = TEST_SECRET + TEXT
                adapter = AnymizeStructuredModel(httpx.MockTransport(lambda request: httpx.Response(status, json=payload)))
                with patch('app.services.anymize_model.get_settings', return_value=settings()):
                    with self.assertLogs('app.services.anymize_model', level='INFO') as logs:
                        with self.assertRaises(ExtractionError) as caught:
                            await adapter.generate('PRIVATE PROMPT', TEXT, FactCandidates)
                self.assertEqual(caught.exception.status_code, public_status)
                output = str(logs.output) + str(caught.exception)
                self.assertIn(category, output)
                for secret in (TEST_SECRET, TEXT, 'PRIVATE PROMPT', 'private_metadata'):
                    self.assertNotIn(secret, output)
                self.assertTrue(all(r.exc_info is None for r in logs.records))
                self.assertIn('elapsed_ms', output)

    async def test_success_diagnostics_safe_tokens_and_validation(self):
        payload = envelope(json.dumps(FACTS))
        payload['usage'] = {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20, 'private': TEXT}
        adapter = AnymizeStructuredModel(httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
        with patch('app.services.anymize_model.get_settings', return_value=settings()):
            with self.assertLogs('app.services.anymize_model', level='INFO') as logs:
                result = await adapter.generate('PRIVATE PROMPT', TEXT, FactCandidates)
        self.assertEqual(json.loads(result), FACTS)
        output = str(logs.output)
        for fragment in ("'schema_validated': True", "'structured_json_parsed': True", "'finish_reason': 'stop'", "'total_tokens': 20"):
            self.assertIn(fragment, output)
        for value in (TEXT, TEST_SECRET, 'PRIVATE PROMPT'):
            self.assertNotIn(value, output)

    async def test_unsafe_finish_reason_and_tokens_are_omitted(self):
        payload = envelope('{}', choices=[{'finish_reason': TEST_SECRET + TEXT, 'message': {'role': 'assistant', 'content': TEXT}}])
        payload['usage'] = {'prompt_tokens': TEXT, 'completion_tokens': True, 'total_tokens': -1}
        adapter = AnymizeStructuredModel(httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
        with patch('app.services.anymize_model.get_settings', return_value=settings()):
            with self.assertLogs('app.services.anymize_model', level='INFO') as logs:
                with self.assertRaises(ExtractionError):
                    await adapter.generate('instruction', TEXT, FactCandidates)
        output = str(logs.output)
        self.assertIn('unrecognized', output)
        for value in (TEST_SECRET, TEXT, 'prompt_tokens', 'completion_tokens', 'total_tokens'):
            self.assertNotIn(value, output)

    async def test_timeout_and_unexpected_errors_have_safe_diagnostics(self):
        for error, category, status in ((httpx.ReadTimeout(TEST_SECRET + TEXT), 'timeout', 504),
                                        (RuntimeError(TEST_SECRET + TEXT), 'unexpected_error', 502)):
            def handle(request):
                raise error
            with patch('app.services.anymize_model.get_settings', return_value=settings()):
                with self.assertLogs('app.services.anymize_model', level='INFO') as logs:
                    with self.assertRaises(ExtractionError) as caught:
                        await AnymizeStructuredModel(httpx.MockTransport(handle)).generate('instruction', TEXT, FactCandidates)
            self.assertEqual(caught.exception.status_code, status)
            self.assertIn(category, str(logs.output))
            self.assertNotIn(TEST_SECRET, str(logs.output))
            self.assertNotIn(TEXT, str(logs.output))

    async def test_non_json_response_is_diagnosed_without_body(self):
        adapter = AnymizeStructuredModel(httpx.MockTransport(lambda request: httpx.Response(200, text=TEST_SECRET + TEXT)))
        with patch('app.services.anymize_model.get_settings', return_value=settings()):
            with self.assertLogs('app.services.anymize_model', level='INFO') as logs:
                with self.assertRaises(ExtractionError) as caught:
                    await adapter.generate('instruction', TEXT, FactCandidates)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("'response_json_exists': False", str(logs.output))
        self.assertIn('invalid_json', str(logs.output))
        self.assertNotIn(TEST_SECRET, str(logs.output))
        self.assertNotIn(TEXT, str(logs.output))
