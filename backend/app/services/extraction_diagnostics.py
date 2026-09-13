"""Request-local extraction diagnostics: fixed metadata only, never payloads."""
from contextvars import ContextVar
import logging
import time

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_context = ContextVar('extraction_diagnostic', default=None)


def begin(index=0):
    return _context.set({'document_index': index, 'started': time.monotonic(),
                         'structured_json_parsed': False, 'schema_validated': False,
                         'evidence_validated': False, 'provenance_validated': False, 'fact_count': 0, 'failure_logged': False})


def end(token):
    _context.reset(token)


def emit(stage, category=None, success=True, **flags):
    state = _context.get()
    if state is None:
        state = {'document_index': 0, 'started': time.monotonic(), 'structured_json_parsed': False,
                 'schema_validated': False, 'evidence_validated': False, 'provenance_validated': False, 'fact_count': 0}
    for key in ('structured_json_parsed', 'schema_validated', 'evidence_validated', 'provenance_validated'):
        if key in flags:
            state[key] = bool(flags[key])
    if 'fact_count' in flags:
        state['fact_count'] = max(0, min(1_000_000, flags['fact_count']))
    if not success:
        state['failure_logged'] = True
    logger.info('Extraction diagnostic %s', {k: v for k, v in state.items() if k not in ('started', 'failure_logged')} | {
        'stage': stage, 'category': category, 'success': success,
        'elapsed_ms': round((time.monotonic() - state['started']) * 1000)})


def validation_failure(error):
    invalid_json = any(item['type'] == 'json_invalid' for item in error.errors(include_input=False, include_context=False))
    emit('structured_json_parse' if invalid_json else 'property_fact_schema_validation',
         'invalid_json' if invalid_json else 'schema_validation_failed', False,
         structured_json_parsed=not invalid_json, schema_validated=False)


def unexpected_failure():
    state = _context.get()
    if state is None or not state.get("failure_logged"):
        emit("model_output_received", "unexpected_extraction_error", False)
