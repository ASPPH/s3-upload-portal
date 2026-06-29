"""Unit tests for CORS handling in Lambda responses (task 2.3)."""

import importlib
import json
import os

import pytest

# Set env vars before importing handler
os.environ.setdefault('UPLOAD_PASSWORD', 'test-secret')
os.environ['ALLOWED_ORIGIN'] = 'https://portal.example.com'
os.environ.setdefault('TARGET_BUCKET', 'test-bucket')

handler_module = importlib.import_module('src.lambda.handler')
build_response = handler_module.build_response
lambda_handler = handler_module.lambda_handler


def make_event(body_dict, origin=None):
    """Helper to create API Gateway proxy event with optional origin header."""
    event = {'body': json.dumps(body_dict)}
    if origin is not None:
        event['headers'] = {'origin': origin}
    else:
        event['headers'] = {}
    return event


class TestBuildResponseCORS:
    def test_matching_origin_includes_cors_headers(self):
        resp = build_response(200, {'ok': True}, origin='https://portal.example.com')
        assert resp['headers']['Access-Control-Allow-Origin'] == 'https://portal.example.com'
        assert resp['headers']['Access-Control-Allow-Methods'] == 'POST, OPTIONS'
        assert resp['headers']['Access-Control-Allow-Headers'] == 'Content-Type'

    def test_non_matching_origin_omits_cors_headers(self):
        resp = build_response(200, {'ok': True}, origin='https://evil.com')
        assert 'Access-Control-Allow-Origin' not in resp['headers']
        assert 'Access-Control-Allow-Methods' not in resp['headers']
        assert 'Access-Control-Allow-Headers' not in resp['headers']

    def test_no_origin_omits_cors_headers(self):
        resp = build_response(200, {'ok': True}, origin=None)
        assert 'Access-Control-Allow-Origin' not in resp['headers']

    def test_empty_origin_omits_cors_headers(self):
        resp = build_response(200, {'ok': True}, origin='')
        assert 'Access-Control-Allow-Origin' not in resp['headers']

    def test_content_type_always_present(self):
        resp = build_response(200, {'ok': True}, origin='https://portal.example.com')
        assert resp['headers']['Content-Type'] == 'application/json'

        resp2 = build_response(200, {'ok': True}, origin='https://evil.com')
        assert resp2['headers']['Content-Type'] == 'application/json'

    def test_cors_headers_on_error_response_with_matching_origin(self):
        resp = build_response(401, {'error': 'Unauthorized'}, origin='https://portal.example.com')
        assert resp['headers']['Access-Control-Allow-Origin'] == 'https://portal.example.com'
        assert resp['statusCode'] == 401


class TestLambdaHandlerCORS:
    def test_origin_passed_to_response_on_auth_failure(self):
        event = make_event({'password': 'wrong'}, origin='https://portal.example.com')
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 401
        assert resp['headers']['Access-Control-Allow-Origin'] == 'https://portal.example.com'

    def test_origin_passed_to_response_on_validation_failure(self):
        event = make_event({'password': 'test-secret'}, origin='https://portal.example.com')
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 400
        assert resp['headers']['Access-Control-Allow-Origin'] == 'https://portal.example.com'

    def test_non_matching_origin_no_cors_on_error(self):
        event = make_event({'password': 'wrong'}, origin='https://attacker.com')
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 401
        assert 'Access-Control-Allow-Origin' not in resp['headers']

    def test_no_headers_in_event(self):
        event = {'body': json.dumps({'password': 'wrong'})}
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 401
        assert 'Access-Control-Allow-Origin' not in resp['headers']

    def test_capital_origin_header(self):
        """API Gateway may pass Origin with capital O."""
        event = {
            'body': json.dumps({'password': 'wrong'}),
            'headers': {'Origin': 'https://portal.example.com'},
        }
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 401
        assert resp['headers']['Access-Control-Allow-Origin'] == 'https://portal.example.com'
