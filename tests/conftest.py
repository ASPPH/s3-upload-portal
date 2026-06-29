"""Shared pytest fixtures for s3-upload-portal Lambda handler tests."""

import importlib
import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Ensure env vars are set before any handler imports
os.environ.setdefault('UPLOAD_PASSWORD', 'test-secret')
os.environ.setdefault('TARGET_BUCKET', 'test-bucket')
os.environ.setdefault('UPLOAD_PREFIX', 'shared/')
os.environ.setdefault('ALLOWED_ORIGIN', 'https://portal.example.com')


@pytest.fixture
def mock_env(monkeypatch):
    """Set environment variables for Lambda handler."""
    monkeypatch.setenv('UPLOAD_PASSWORD', 'test-secret')
    monkeypatch.setenv('TARGET_BUCKET', 'test-bucket')
    monkeypatch.setenv('UPLOAD_PREFIX', 'shared/')
    monkeypatch.setenv('ALLOWED_ORIGIN', 'https://portal.example.com')


@pytest.fixture
def mock_s3_client():
    """Patch boto3.client to return a mock S3 client with a fake presigned URL."""
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = (
        'https://test-bucket.s3.amazonaws.com/shared/test.pdf'
        '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=300'
    )
    with patch('boto3.client', return_value=mock_client) as mock_boto3:
        yield mock_client


@pytest.fixture
def valid_event():
    """Create a valid API Gateway proxy event for a PDF upload."""
    return make_event({
        'password': 'test-secret',
        'filename': 'report.pdf',
        'contentType': 'application/pdf',
        'fileSize': 5000,
    })


@pytest.fixture
def make_event_fixture():
    """Provide the make_event helper as a fixture."""
    return make_event


def make_event(body_dict, origin=None):
    """Helper to create an API Gateway proxy event.

    Args:
        body_dict: Dictionary to serialize as the request body.
        origin: Optional origin header value for CORS testing.

    Returns:
        A dict mimicking an API Gateway Lambda proxy integration event.
    """
    event = {'body': json.dumps(body_dict)}
    if origin is not None:
        event['headers'] = {'origin': origin}
    else:
        event['headers'] = {}
    return event
