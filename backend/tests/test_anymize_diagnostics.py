"""Safe OCR diagnostics; all data and credentials are synthetic."""
import os
import unittest
from unittest.mock import patch

import httpx

from app.config import Settings, get_settings
from app.services.anymize import AnymizeError, AnymizeService


class OcrDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, responses, expected_status=None):
        settings = Settings(_env_file=None, anymize_api_key='synthetic-secret-sentinel')
        def handle(request):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        service = AnymizeService(httpx.MockTransport(handle))
        service.POLL_INTERVAL = 0
        with patch('app.services.anymize.get_settings', return_value=settings):
            with self.assertLogs('app.services.anymize', level='INFO') as logs:
                if expected_status:
                    with self.assertRaises(AnymizeError) as error:
                        await service.anonymize_pdf(b'%PDF-synthetic-private-content')
                    self.assertEqual(error.exception.status_code, expected_status)
                else:
                    await service.anonymize_pdf(b'%PDF-synthetic-private-content')
        output = '\n'.join(logs.output)
        for forbidden in ('synthetic-secret-sentinel', 'SENSITIVE_SENTINEL', 'synthetic-private-content', 'safe-job-id', 'authorization'):
            self.assertNotIn(forbidden.lower(), output.lower())
        self.assertTrue(all(record.exc_info is None for record in logs.records))
        return output

    async def test_start_rejection_status_is_visible_without_body(self):
        output = await self.invoke([httpx.Response(401, text='SENSITIVE_SENTINEL')], 502)
        for value in ('ocr_start', 'http_rejected', "'http_status': 401", "'key_configured': True"):
            self.assertIn(value, output)

    async def test_poll_failure_is_separate_from_start(self):
        output = await self.invoke([httpx.Response(202, json={'job_id': 'safe-job-id'}), httpx.Response(500, text='SENSITIVE_SENTINEL')], 502)
        self.assertIn('ocr_poll', output)
        self.assertIn("'http_status': 500", output)

    async def test_missing_expected_result_reports_presence_only(self):
        output = await self.invoke([httpx.Response(202, json={'job_id': 'safe-job-id'}), httpx.Response(200, json={
            'status': 'completed', 'anonymized_text': 'SENSITIVE_SENTINEL', 'original_text': 'SENSITIVE_SENTINEL'
        })], 502)
        for value in ('ocr_result', 'unusable_result', "'has_expected_text': False", "'has_alternate_text': True"):
            self.assertIn(value, output)

    async def test_unknown_status_and_untrusted_keys_are_never_logged(self):
        output = await self.invoke([httpx.Response(202, json={'job_id': 'safe-job-id'}), httpx.Response(200, json={
            'status': 'SENSITIVE_SENTINEL', 'SENSITIVE_SENTINEL': 'SENSITIVE_SENTINEL'
        })], 502)
        self.assertIn('unrecognized', output)
        self.assertIn('unexpected_job_status', output)

    async def test_success_reports_no_document_text(self):
        output = await self.invoke([httpx.Response(202, json={'job_id': 'safe-job-id'}), httpx.Response(200, json={
            'status': 'completed', 'anonymized_text_raw': 'SENSITIVE_SENTINEL', 'original_text': 'SENSITIVE_SENTINEL'
        })])
        self.assertIn("'has_expected_text': True", output)
        self.assertIn('ocr_result', output)

    async def test_invalid_json_envelope_job_and_transport_have_categories(self):
        for response, category, status in (
            (httpx.Response(202, text='SENSITIVE_SENTINEL'), 'invalid_json', 502),
            (httpx.Response(202, json=[]), 'invalid_envelope', 502),
            (httpx.Response(202, json={'job_id': 'SENSITIVE_SENTINEL/'}), 'invalid_job_id', 502),
            (httpx.ConnectError('SENSITIVE_SENTINEL'), 'transport_error', 502),
            (httpx.ReadTimeout('SENSITIVE_SENTINEL'), 'timeout', 504),
            (RuntimeError('SENSITIVE_SENTINEL'), 'unexpected_error', 502),
        ):
            with self.subTest(category=category):
                output = await self.invoke([response], status)
                self.assertIn(category, output)

    async def test_production_environment_key_reaches_ocr_without_env_file(self):
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        with patch.dict(os.environ, {'APP_ENV': 'production', 'ANYMIZE_API_KEY': 'synthetic-secret-sentinel'}, clear=True):
            settings = get_settings()
            self.assertEqual(settings.anymize_api_key.get_secret_value(), 'synthetic-secret-sentinel')
            self.assertIsNone(settings.model_config['env_file'])
            self.assertNotIn('synthetic-secret-sentinel', repr(settings))
            self.assertNotIn('synthetic-secret-sentinel', settings.model_dump_json())
            def handle(request):
                self.assertEqual(request.headers['authorization'], 'Bearer synthetic-secret-sentinel')
                return httpx.Response(401)
            with self.assertLogs('app.services.anymize', level='WARNING') as logs:
                with self.assertRaises(AnymizeError):
                    await AnymizeService(httpx.MockTransport(handle)).anonymize_pdf(b'%PDF-synthetic')
            self.assertNotIn('synthetic-secret-sentinel', str(logs.output))


class OcrJobIdRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_safe_ids_poll_exact_path_and_return_anonymized_result(self):
        for job_id in ('job_ocr789xyz012', 'demo-job-123', 'abc123', 'a' * 128):
            with self.subTest(job_id=job_id):
                calls = []
                def handle(request):
                    calls.append((request.method, str(request.url)))
                    if request.method == 'POST':
                        return httpx.Response(202, json={'job_id': job_id, 'status': 'processing'})
                    return httpx.Response(200, json={'status': 'completed',
                        'anonymized_text_raw': 'Synthetic anonymized result',
                        'original_text': 'SENSITIVE_SENTINEL'})
                with patch('app.services.anymize.get_settings', return_value=Settings(_env_file=None, anymize_api_key='synthetic-test-key')):
                    result = await AnymizeService(httpx.MockTransport(handle)).anonymize_pdf(b'%PDF-synthetic')
                self.assertEqual(result, 'Synthetic anonymized result')
                self.assertEqual(calls, [('POST', 'https://app.anymize.ai/api/ocr'),
                                        ('GET', 'https://app.anymize.ai/api/status/' + job_id)])

    async def test_unsafe_ids_fail_before_poll_without_leaking_values(self):
        for job_id in ('a/b', r'a\b', 'a?query', 'a#fragment', 'a%2Fb', 'a b', 'a\t', 'a\n',
                       'a\r', 'a\x00', 'a\x7f', '../path', 'a:b', 'a@b', 'ä', '',
                       'a' * 129, None, 123, 'synthetic-test-key', 'prefix_synthetic-test-key_suffix'):
            with self.subTest():
                calls = []
                def handle(request):
                    calls.append(request.method)
                    return httpx.Response(202, json={'job_id': job_id})
                with patch('app.services.anymize.get_settings', return_value=Settings(_env_file=None, anymize_api_key='synthetic-test-key')):
                    with self.assertLogs('app.services.anymize', level='WARNING') as logs:
                        with self.assertRaises(AnymizeError) as error:
                            await AnymizeService(httpx.MockTransport(handle)).anonymize_pdf(b'%PDF-synthetic')
                self.assertEqual(error.exception.status_code, 502)
                self.assertEqual(str(error.exception), 'Document processor returned an invalid job.')
                self.assertEqual(calls, ['POST'])
                self.assertIn('invalid_job_id', str(logs.output))
                self.assertNotIn('synthetic-test-key', str(logs.output))
                self.assertTrue(all(r.exc_info is None for r in logs.records))
