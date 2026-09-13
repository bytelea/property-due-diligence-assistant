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
            'status': 'SENSITIVE_SENTINEL/', 'SENSITIVE_SENTINEL': 'SENSITIVE_SENTINEL'
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


class PendingOcrTests(unittest.IsolatedAsyncioTestCase):
    async def run_sequence(self, statuses, expected_error=None, repeat_pending=False, repeat_status="pending"):
        calls = []
        polls = []
        secret = 'synthetic-pending-secret'
        job_id = 'synthetic_pending_job'
        def handle(request):
            calls.append(request.method)
            if request.method == 'POST':
                return httpx.Response(202, json={'job_id': job_id})
            status = repeat_status if repeat_pending else statuses[len(polls)]
            polls.append(status)
            payload = {'status': status, 'job_id': job_id,
                       'original_text': 'PRIVATE_SENTINEL', 'metadata': 'PAYLOAD_SENTINEL'}
            if isinstance(status, str) and status.strip().lower() == 'completed' and expected_error is None:
                payload['anonymized_text_raw'] = 'ANONYMIZED_SENTINEL'
            return httpx.Response(200, json=payload)
        service = AnymizeService(httpx.MockTransport(handle))
        service.POLL_INTERVAL = 0.001 if repeat_pending else 0
        if repeat_pending:
            service.PROCESSING_TIMEOUT = 0.05
        with patch('app.services.anymize.get_settings', return_value=Settings(_env_file=None, anymize_api_key=secret)):
            with self.assertLogs('app.services.anymize', level='INFO') as logs:
                if expected_error:
                    with self.assertRaises(AnymizeError) as error:
                        await service.anonymize_pdf(b'%PDF-PRIVATE_SENTINEL')
                    self.assertEqual(error.exception.status_code, expected_error)
                    public_error = str(error.exception)
                    self.assertTrue(error.exception.__suppress_context__ if expected_error == 504 else True)
                else:
                    result = await service.anonymize_pdf(b'%PDF-PRIVATE_SENTINEL')
                    self.assertEqual(result, 'ANONYMIZED_SENTINEL')
                    public_error = ''
        output = '\n'.join(logs.output) + public_error
        for forbidden in (secret, job_id, 'PRIVATE_SENTINEL', 'ANONYMIZED_SENTINEL', 'PAYLOAD_SENTINEL', 'authorization'):
            self.assertNotIn(forbidden, output)
        self.assertTrue(all(r.exc_info is None for r in logs.records))
        self.assertEqual(calls[0], 'POST')
        self.assertTrue(all(method == 'GET' for method in calls[1:]))
        return polls, output

    async def test_pending_processing_completed(self):
        statuses = ['pending', 'processing', 'completed']
        polls, output = await self.run_sequence(statuses)
        self.assertEqual(polls, statuses)
        self.assertIn("'job_status': 'pending'", output)

    async def test_pending_completed(self):
        statuses = ['pending', 'completed']
        polls, _ = await self.run_sequence(statuses)
        self.assertEqual(polls, statuses)

    async def test_repeated_pending_reaches_existing_deadline(self):
        polls, output = await self.run_sequence([], expected_error=504, repeat_pending=True)
        self.assertGreaterEqual(len(polls), 2)
        self.assertEqual(set(polls), {'pending'})
        self.assertIn("'category': 'timeout'", output)

    async def test_pending_then_unknown_or_failed_still_fails(self):
        for status in ('PRIVATE_SENTINEL', 'failed', 'error', 'queued', None):
            with self.subTest(status=status):
                polls, output = await self.run_sequence(['pending', status], expected_error=502)
                self.assertEqual(polls, ['pending', status])
                self.assertIn('unexpected_job_status', output)

    async def test_pending_completed_without_expected_text_fails(self):
        polls, output = await self.run_sequence(['pending', 'completed'], expected_error=502)
        self.assertEqual(polls, ['pending', 'completed'])
        self.assertIn('unusable_result', output)


    async def test_extracting_processing_completed(self):
        statuses = ['pass1_extracting', 'processing', 'completed']
        polls, _ = await self.run_sequence(statuses)
        self.assertEqual(polls, statuses)

    async def test_extracting_completed(self):
        statuses = ['pass1_extracting', 'completed']
        polls, _ = await self.run_sequence(statuses)
        self.assertEqual(polls, statuses)

    async def test_repeated_extracting_times_out(self):
        polls, output = await self.run_sequence([], expected_error=504, repeat_pending=True, repeat_status='pass1_extracting')
        self.assertGreaterEqual(len(polls), 2)
        self.assertEqual(set(polls), {'pass1_extracting'})
        self.assertIn("'category': 'timeout'", output)

    async def test_case_and_whitespace_normalize_all_recognized_states(self):
        statuses = [' PENDING ', '\tPASS1_EXTRACTING\n', ' Processing ', ' COMPLETED\r\n']
        polls, _ = await self.run_sequence(statuses)
        self.assertEqual(polls, statuses)

    async def test_extracting_then_unknown_or_failure_still_fails(self):
        for status in (' NEW_STATE ', ' FAILED ', ' ERROR ', None, 123, {}, []):
            with self.subTest(status=status):
                polls, output = await self.run_sequence(['pass1_extracting', status], expected_error=502)
                self.assertEqual(polls, ['pass1_extracting', status])
                self.assertIn('unexpected_job_status', output)

    async def test_normalized_completed_still_requires_expected_text(self):
        _, output = await self.run_sequence(['pass1_extracting', ' COMPLETED '], expected_error=502)
        self.assertIn('unusable_result', output)

    async def test_second_pass_processing_completed(self):
        statuses = ['pass2_extracting', 'processing', 'completed']
        polls, _ = await self.run_sequence(statuses)
        self.assertEqual(polls, statuses)

    async def test_first_pass_second_pass_completed(self):
        statuses = ['pass1_extracting', 'pass2_extracting', 'completed']
        polls, _ = await self.run_sequence(statuses)
        self.assertEqual(polls, statuses)

    async def test_repeated_second_pass_times_out(self):
        polls, output = await self.run_sequence([], expected_error=504, repeat_pending=True, repeat_status='pass2_extracting')
        self.assertGreaterEqual(len(polls), 2)
        self.assertEqual(set(polls), {'pass2_extracting'})
        self.assertIn("'category': 'timeout'", output)

    async def test_second_pass_case_and_whitespace_normalization(self):
        statuses = ['  PASS2_EXTRACTING\t', ' Processing ', ' COMPLETED\n']
        polls, _ = await self.run_sequence(statuses)
        self.assertEqual(polls, statuses)

    async def test_second_pass_unknown_status_still_fails(self):
        for status in ('pass3_extracting', 'unknown', ' FAILED ', 'error', None):
            with self.subTest(status=status):
                polls, output = await self.run_sequence(['pass2_extracting', status], expected_error=502)
                self.assertEqual(polls, ['pass2_extracting', status])
                self.assertIn('unexpected_job_status', output)


class ValidatedStatusDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def check_status(self, raw, expected):
        calls = []
        def handle(request):
            calls.append(request.method)
            if request.method == 'POST':
                return httpx.Response(202, json={'job_id': 'synthetic-job-id'})
            return httpx.Response(200, json={'status': raw, 'original_text': 'PRIVATE BODY',
                                            'anonymized_text_raw': 'PRIVATE ANONYMIZED BODY'})
        with patch('app.services.anymize.get_settings', return_value=Settings(_env_file=None, anymize_api_key='synthetic-secret-key')):
            with self.assertLogs('app.services.anymize', level='WARNING') as logs:
                with self.assertRaises(AnymizeError) as error:
                    await AnymizeService(httpx.MockTransport(handle)).anonymize_pdf(b'%PDF-PRIVATE BODY')
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(calls, ['POST', 'GET'])
        self.assertIn("'job_status': " + repr(expected), logs.output[0])
        for value in ('synthetic-secret-key', 'synthetic-job-id', 'PRIVATE BODY', 'PRIVATE ANONYMIZED BODY'):
            self.assertNotIn(value, str(logs.output) + str(error.exception))
        self.assertTrue(all(r.exc_info is None for r in logs.records))

    async def test_safe_metadata_is_normalized_for_logging(self):
        for raw, expected in (('  NEW_STATE-2  ', 'new_state-2'), ('a' * 32, 'a' * 32), ('RUNNING', 'running')):
            await self.check_status(raw, expected)

    async def test_invalid_metadata_is_hidden(self):
        for raw in (None, 123, [], {}, '', ' ', 'a' * 33, 'bad/status', 'bad?status',
                    'bad#status', 'bad%status', 'bad status', 'bad\x00status', 'bad\nstatus', 'ÜBER'):
            await self.check_status(raw, 'unrecognized')

    async def test_reflected_credentials_and_job_ids_are_hidden(self):
        for raw in ('synthetic-secret-key', 'SYNTHETIC-JOB-ID'):
            await self.check_status(raw, 'unrecognized')

    async def test_normalized_unknown_states_still_fail(self):
        for raw in (' UNKNOWN ', 'FAILED', ' Error '):
            await self.check_status(raw, raw.strip().lower())
