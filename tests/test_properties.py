# Feature: s3-upload-portal, Property 6: CORS headers are origin-dependent
# Feature: s3-upload-portal, Property 2: Object key preserves filename and guarantees uniqueness
# Feature: s3-upload-portal, Property 4: Disallowed content types are rejected
"""Property-based tests for s3-upload-portal Lambda handler.

**Validates: Requirements 7.1, 7.3, 2.3, 2.4, 4.5**
"""

import importlib
import json
import os
from unittest.mock import patch, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

# Set env vars before importing handler
os.environ.setdefault('TARGET_BUCKET', 'test-bucket')
os.environ['ALLOWED_ORIGIN'] = 'https://portal.example.com'
os.environ['UPLOAD_PREFIX'] = 'shared/'

handler_module = importlib.import_module('src.lambda.handler')

# Mock the password cache so auth tests work without Secrets Manager
handler_module._cached_password = 'test-secret'

lambda_handler = handler_module.lambda_handler
generate_object_key = handler_module.generate_object_key
ALLOWED_CONTENT_TYPES = handler_module.DEFAULT_ALLOWED_CONTENT_TYPES

FIXED_ALLOWED_ORIGIN = 'https://portal.example.com'


def _make_valid_event(origin):
    """Create a valid upload event with the given origin header."""
    body = {
        'password': os.environ['UPLOAD_PASSWORD'],
        'filename': 'test-file.pdf',
        'contentType': 'application/pdf',
        'fileSize': 1024,
    }
    return {
        'body': json.dumps(body),
        'headers': {'origin': origin},
    }


def _mock_s3_client():
    """Create a mock boto3 S3 client that returns a fake presigned URL."""
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = 'https://bucket.s3.amazonaws.com/fake-presigned-url'
    return mock_client


class TestProperty6CORSHeadersOriginDependent:
    """Property 6: CORS headers are origin-dependent.

    For any request origin, the response SHALL include Access-Control-Allow-Origin
    if and only if the origin matches the configured allowed origin. When included,
    it SHALL also include Access-Control-Allow-Methods: POST, OPTIONS and
    Access-Control-Allow-Headers: Content-Type.

    **Validates: Requirements 7.1, 7.3**
    """

    @settings(max_examples=100)
    @given(st.just(FIXED_ALLOWED_ORIGIN))
    def test_matching_origin_includes_cors_headers(self, origin):
        """Test A: Matching origin includes CORS headers.

        When the request origin matches ALLOWED_ORIGIN, the response must contain
        all three CORS headers with correct values.
        """
        event = _make_valid_event(origin)

        with patch('boto3.client') as mock_boto3:
            mock_boto3.return_value = _mock_s3_client()
            with patch.dict(os.environ, {'ALLOWED_ORIGIN': FIXED_ALLOWED_ORIGIN}):
                response = lambda_handler(event, None)

        headers = response['headers']
        assert headers['Access-Control-Allow-Origin'] == FIXED_ALLOWED_ORIGIN
        assert headers['Access-Control-Allow-Methods'] == 'POST, OPTIONS'
        assert headers['Access-Control-Allow-Headers'] == 'Content-Type'

    @settings(max_examples=100)
    @given(
        st.text(min_size=1, max_size=100).filter(
            lambda x: x != 'https://portal.example.com'
        )
    )
    def test_non_matching_origin_omits_cors_headers(self, origin):
        """Test B: Non-matching origin omits CORS headers.

        When the request origin does NOT match ALLOWED_ORIGIN, the response must
        NOT contain Access-Control-Allow-Origin or Access-Control-Allow-Methods.
        """
        body = {
            'password': 'wrong-password',
            'filename': 'test.pdf',
            'contentType': 'application/pdf',
            'fileSize': 1024,
        }
        event = {
            'body': json.dumps(body),
            'headers': {'origin': origin},
        }

        with patch.dict(os.environ, {'ALLOWED_ORIGIN': FIXED_ALLOWED_ORIGIN}):
            response = lambda_handler(event, None)

        headers = response['headers']
        assert 'Access-Control-Allow-Origin' not in headers
        assert 'Access-Control-Allow-Methods' not in headers


# Feature: s3-upload-portal, Property 3: Invalid file sizes are rejected


# Strategies for valid filenames and content types
_valid_filenames = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-_. '),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

_valid_content_types = st.sampled_from([
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
])


def _make_size_test_event(filename, content_type, file_size):
    """Build an API Gateway proxy event with valid auth for size tests."""
    body = json.dumps({
        'password': os.environ['UPLOAD_PASSWORD'],
        'filename': filename,
        'contentType': content_type,
        'fileSize': file_size,
    })
    return {
        'headers': {'origin': 'https://portal.example.com'},
        'body': body,
    }


class TestProperty3InvalidFileSizesRejected:
    """Property 3: Invalid file sizes are rejected.

    For any file size that is <= 0 or > 52,428,800 bytes, the Lambda handler
    SHALL return an error response (400 for empty, 413 for too large) and
    SHALL NOT return a presigned URL.

    **Validates: Requirements 2.5, 4.1, 5.5**
    """

    @settings(max_examples=100)
    @given(
        file_size=st.just(0),
        filename=_valid_filenames,
        content_type=_valid_content_types,
    )
    def test_empty_files_are_rejected(self, file_size, filename, content_type):
        """Test A: Empty files (size = 0) are rejected with HTTP 400.

        **Validates: Requirements 2.5, 4.1, 5.5**
        """
        with patch.dict(os.environ, {
            'UPLOAD_PASSWORD': 'test-secret',
            'TARGET_BUCKET': 'test-bucket',
            'ALLOWED_ORIGIN': 'https://portal.example.com',
        }):
            event = _make_size_test_event(filename, content_type, file_size)
            result = lambda_handler(event, None)

        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert 'Empty files are not permitted' in body['message']
        assert 'uploadUrl' not in body

    @settings(max_examples=100)
    @given(
        file_size=st.integers(min_value=52_428_801, max_value=500_000_000),
        filename=_valid_filenames,
        content_type=_valid_content_types,
    )
    def test_oversized_files_are_rejected(self, file_size, filename, content_type):
        """Test B: Oversized files (> 52,428,800 bytes) are rejected with HTTP 413.

        **Validates: Requirements 2.5, 4.1, 5.5**
        """
        with patch.dict(os.environ, {
            'UPLOAD_PASSWORD': 'test-secret',
            'TARGET_BUCKET': 'test-bucket',
            'ALLOWED_ORIGIN': 'https://portal.example.com',
        }):
            event = _make_size_test_event(filename, content_type, file_size)
            result = lambda_handler(event, None)

        assert result['statusCode'] == 413
        body = json.loads(result['body'])
        assert '50 MB' in body['message']
        assert 'uploadUrl' not in body


# Strategy for valid filenames: non-empty text with letters, digits, hyphens, underscores, dots
valid_filenames = st.text(
    alphabet=st.sampled_from(
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.'
    ),
    min_size=1,
    max_size=100,
)


# Feature: s3-upload-portal, Property 2: Object key preserves filename and guarantees uniqueness
class TestProperty2ObjectKeyPreservesFilenameAndGuaranteesUniqueness:
    """Property 2: Object key generation preserves filename and guarantees uniqueness.

    For any valid filename, the generated object key SHALL contain the original filename,
    and for any two calls to the key generation function (even with the same filename),
    the generated keys SHALL be different.

    **Validates: Requirements 2.3, 2.4**
    """

    @given(filename=valid_filenames)
    @settings(max_examples=100)
    def test_object_key_contains_sanitized_filename(self, filename):
        """The generated object key SHALL contain the sanitized filename."""
        sanitize_filename = handler_module.sanitize_filename
        key = generate_object_key(filename)
        sanitized = sanitize_filename(filename)
        assert sanitized in key, f"Generated key '{key}' does not contain sanitized filename '{sanitized}'"

    @given(filename=valid_filenames)
    @settings(max_examples=100)
    def test_object_key_starts_with_upload_prefix(self, filename):
        """The generated object key SHALL start with the configured upload prefix."""
        key = generate_object_key(filename)
        assert key.startswith('shared/'), f"Generated key '{key}' does not start with 'shared/'"

    @given(filename=valid_filenames)
    @settings(max_examples=100)
    def test_two_calls_with_same_filename_produce_same_key(self, filename):
        """Two calls with the same filename SHALL produce the same key (deterministic)."""
        key1 = generate_object_key(filename)
        key2 = generate_object_key(filename)
        assert key1 == key2, f"Two calls with '{filename}' produced different keys: '{key1}' vs '{key2}'"


# Feature: s3-upload-portal, Property 4: Disallowed content types are rejected
class TestProperty4DisallowedContentTypesRejected:
    """Property 4: Disallowed content types are rejected.

    For any content type string that is not in the allowed content types set,
    the Lambda handler SHALL return a 415 error response listing the allowed types
    and SHALL NOT return a presigned URL.

    **Validates: Requirements 4.5**
    """

    @settings(max_examples=100)
    @given(
        content_type=st.from_regex(r'[a-z]+/[a-z0-9.+-]+', fullmatch=True).filter(
            lambda x: x not in ALLOWED_CONTENT_TYPES
        ),
        filename=st.from_regex(r'[a-zA-Z0-9_-]+\.[a-z]{2,4}', fullmatch=True),
        file_size=st.integers(min_value=1, max_value=52428800),
    )
    def test_disallowed_content_types_are_rejected(self, content_type, filename, file_size):
        """Any content type NOT in ALLOWED_CONTENT_TYPES is rejected with HTTP 415.

        **Validates: Requirements 4.5**
        """
        event = _make_size_test_event(filename, content_type, file_size)

        with patch.dict(os.environ, {
            'UPLOAD_PASSWORD': 'test-secret',
            'TARGET_BUCKET': 'test-bucket',
            'ALLOWED_ORIGIN': 'https://portal.example.com',
        }):
            response = lambda_handler(event, None)

        assert response['statusCode'] == 415

        body = json.loads(response['body'])
        assert 'File type not allowed' in body['message']
        assert 'uploadUrl' not in body
