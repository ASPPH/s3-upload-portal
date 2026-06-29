"""Unit tests for Lambda handler auth and validation (task 2.1)."""

import importlib
import json
import os
import sys

import pytest

# Set env var before importing handler
os.environ['TARGET_BUCKET'] = 'test-bucket'

# 'lambda' is a Python keyword, so use importlib to import the module
handler_module = importlib.import_module('src.lambda.handler')

# Mock the password cache so auth tests work without Secrets Manager
handler_module._cached_password = 'test-secret'

ALLOWED_CONTENT_TYPES = handler_module.DEFAULT_ALLOWED_CONTENT_TYPES
MAX_FILE_SIZE = handler_module.MAX_FILE_SIZE
build_response = handler_module.build_response
lambda_handler = handler_module.lambda_handler
validate_auth = handler_module.validate_auth
validate_request = handler_module.validate_request


def make_event(body_dict):
    """Helper to create API Gateway proxy event."""
    return {'body': json.dumps(body_dict)}


class TestValidateAuth:
    def test_valid_password(self):
        event = make_event({'password': 'test-secret'})
        assert validate_auth(event) is True

    def test_invalid_password(self):
        event = make_event({'password': 'wrong'})
        assert validate_auth(event) is False

    def test_missing_password(self):
        event = make_event({})
        assert validate_auth(event) is False

    def test_no_body(self):
        event = {'body': None}
        assert validate_auth(event) is False

    def test_malformed_json(self):
        event = {'body': 'not json'}
        assert validate_auth(event) is False


class TestValidateRequest:
    def test_valid_request(self):
        body = {'filename': 'report.pdf', 'contentType': 'application/pdf', 'fileSize': 1024}
        code, error = validate_request(body)
        assert code is None
        assert error is None

    def test_missing_filename(self):
        body = {'contentType': 'application/pdf', 'fileSize': 1024}
        code, error = validate_request(body)
        assert code == 400
        assert 'filename and contentType are required' in error['message']

    def test_empty_filename(self):
        body = {'filename': '', 'contentType': 'application/pdf', 'fileSize': 1024}
        code, error = validate_request(body)
        assert code == 400

    def test_missing_content_type(self):
        body = {'filename': 'report.pdf', 'fileSize': 1024}
        code, error = validate_request(body)
        assert code == 400

    def test_empty_file(self):
        body = {'filename': 'report.pdf', 'contentType': 'application/pdf', 'fileSize': 0}
        code, error = validate_request(body)
        assert code == 400
        assert 'Empty files are not permitted' in error['message']

    def test_file_too_large(self):
        body = {'filename': 'report.pdf', 'contentType': 'application/pdf', 'fileSize': MAX_FILE_SIZE + 1}
        code, error = validate_request(body)
        assert code == 413
        assert '50 MB' in error['message']

    def test_file_exactly_max_size(self):
        body = {'filename': 'report.pdf', 'contentType': 'application/pdf', 'fileSize': MAX_FILE_SIZE}
        code, error = validate_request(body)
        assert code is None

    def test_disallowed_content_type(self):
        body = {'filename': 'script.exe', 'contentType': 'application/x-msdownload', 'fileSize': 1024}
        code, error = validate_request(body)
        assert code == 415
        assert 'File type not allowed' in error['message']

    def test_all_allowed_types_pass(self):
        for ct in ALLOWED_CONTENT_TYPES:
            body = {'filename': 'file.bin', 'contentType': ct, 'fileSize': 1024}
            code, error = validate_request(body)
            assert code is None, f'{ct} should be allowed'


class TestLambdaHandler:
    def test_unauthorized(self):
        event = make_event({'password': 'wrong', 'filename': 'f.pdf', 'contentType': 'application/pdf', 'fileSize': 100})
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 401
        body = json.loads(resp['body'])
        assert body['error'] == 'Unauthorized'

    def test_bad_request_missing_fields(self):
        event = make_event({'password': 'test-secret'})
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 400

    def test_file_too_large_via_handler(self):
        event = make_event({
            'password': 'test-secret',
            'filename': 'big.pdf',
            'contentType': 'application/pdf',
            'fileSize': MAX_FILE_SIZE + 1,
        })
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 413

    def test_unsupported_media_type_via_handler(self):
        event = make_event({
            'password': 'test-secret',
            'filename': 'virus.exe',
            'contentType': 'application/x-msdownload',
            'fileSize': 1024,
        })
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 415

    def test_valid_request_passes_validation(self):
        event = make_event({
            'password': 'test-secret',
            'filename': 'report.pdf',
            'contentType': 'application/pdf',
            'fileSize': 5000,
        })
        resp = lambda_handler(event, None)
        assert resp['statusCode'] == 200

    def test_s3_error_returns_500(self):
        from unittest.mock import patch, MagicMock
        from botocore.exceptions import ClientError
        event = make_event({
            'password': 'test-secret',
            'filename': 'report.pdf',
            'contentType': 'application/pdf',
            'fileSize': 5000,
        })
        with patch('boto3.client') as mock_boto3:
            mock_client = mock_boto3.return_value
            # head_object returns 404 (file doesn't exist) so we proceed to presigned URL
            mock_client.head_object.side_effect = ClientError(
                {'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadObject'
            )
            mock_client.generate_presigned_url.side_effect = Exception('S3 service error')
            resp = lambda_handler(event, None)
        assert resp['statusCode'] == 500
        body = json.loads(resp['body'])
        assert body['error'] == 'Internal Server Error'
        assert 'Failed to generate upload URL' in body['message']
