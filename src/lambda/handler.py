"""Lambda handler for S3 Upload Portal presigned URL generation."""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Cache the password to avoid hitting Secrets Manager on every invocation
_cached_password = None


def get_upload_password():
    """Retrieve upload password from Secrets Manager with caching."""
    global _cached_password
    if _cached_password is not None:
        return _cached_password

    secret_arn = os.environ.get('PASSWORD_SECRET_ARN')
    if not secret_arn:
        return None

    try:
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=secret_arn)
        _cached_password = response['SecretString']
        return _cached_password
    except ClientError:
        return None

DEFAULT_ALLOWED_CONTENT_TYPES = {
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
}


def get_allowed_content_types():
    """Get allowed content types from environment variable or use defaults.

    ALLOWED_CONTENT_TYPES env var should be a comma-separated list of MIME types.
    Example: "application/pdf" or "application/pdf,image/jpeg,image/png"
    """
    env_types = os.environ.get('ALLOWED_CONTENT_TYPES', '')
    if env_types.strip():
        return {t.strip() for t in env_types.split(',') if t.strip()}
    return DEFAULT_ALLOWED_CONTENT_TYPES

MAX_FILE_SIZE = 52_428_800  # 50 MB


def build_response(status_code, body, origin=None):
    """Build an API Gateway compatible HTTP response with conditional CORS headers."""
    headers = {'Content-Type': 'application/json'}

    allowed_origin = os.environ.get('ALLOWED_ORIGIN', '')
    if origin and allowed_origin and origin == allowed_origin:
        headers['Access-Control-Allow-Origin'] = origin
        headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        headers['Access-Control-Allow-Headers'] = 'Content-Type'

    return {
        'statusCode': status_code,
        'headers': headers,
        'body': json.dumps(body),
    }


def validate_auth(event):
    """Validate shared password from request body against Secrets Manager value.

    Returns True if valid, False otherwise.
    """
    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError):
        return False

    password = get_upload_password()
    if not password:
        return False

    return body.get('password') == password


def validate_request(body):
    """Validate upload request fields.

    Returns (None, None) on success, or (status_code, error_body) on failure.
    """
    filename = body.get('filename')
    content_type = body.get('contentType')
    file_size = body.get('fileSize')

    # Check required fields
    if not filename or not content_type:
        return 400, {
            'error': 'Bad Request',
            'message': 'filename and contentType are required',
        }

    # Check empty file
    if file_size is not None and file_size == 0:
        return 400, {
            'error': 'Bad Request',
            'message': 'Empty files are not permitted',
        }

    # Check file too large
    if file_size is not None and file_size > MAX_FILE_SIZE:
        return 413, {
            'error': 'Payload Too Large',
            'message': 'File exceeds maximum size of 50 MB',
        }

    # Check allowed content type
    allowed_types = get_allowed_content_types()
    if content_type not in allowed_types:
        allowed_list = ', '.join(sorted(allowed_types))
        return 415, {
            'error': 'Unsupported Media Type',
            'message': f'File type not allowed. Allowed types: {allowed_list}',
        }

    return None, None


def generate_object_key(filename):
    """Generate S3 object key using the original filename.

    Format: {prefix}{original_filename}
    Example: uploads/annual-report.pdf
    """
    prefix = os.environ.get('UPLOAD_PREFIX', 'uploads/')
    return f'{prefix}{filename}'


def check_object_exists(bucket, key):
    """Check if an object already exists in S3.

    Returns True if the object exists, False otherwise.
    """
    try:
        s3_client = boto3.client('s3')
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        return False


def lambda_handler(event, context):
    """Main Lambda entry point for presigned URL generation."""
    # Extract request origin for CORS handling
    headers = event.get('headers', {}) or {}
    origin = headers.get('origin', '') or headers.get('Origin', '')

    # Validate authentication
    if not validate_auth(event):
        return build_response(401, {
            'error': 'Unauthorized',
            'message': 'Invalid credentials',
        }, origin)

    # Parse request body
    try:
        body = json.loads(event.get('body', '{}'))
    except (json.JSONDecodeError, TypeError):
        return build_response(400, {
            'error': 'Bad Request',
            'message': 'Invalid request body',
        }, origin)

    # Validate request fields
    error_code, error_body = validate_request(body)
    if error_code:
        return build_response(error_code, error_body, origin)

    # Generate object key
    bucket = os.environ.get('TARGET_BUCKET')
    content_type = body.get('contentType')
    filename = body.get('filename')
    confirm_overwrite = body.get('confirmOverwrite', False)
    object_key = generate_object_key(filename)

    # Check if file already exists
    if not confirm_overwrite and check_object_exists(bucket, object_key):
        public_url = f'https://upload.aspph.org/{object_key}'
        return build_response(409, {
            'error': 'Conflict',
            'message': f'A file named "{filename}" already exists.',
            'existingUrl': public_url,
            'objectKey': object_key,
        }, origin)

    try:
        s3_client = boto3.client('s3')
        upload_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket,
                'Key': object_key,
                'ContentType': content_type,
            },
            ExpiresIn=300,
        )
    except Exception:
        return build_response(500, {
            'error': 'Internal Server Error',
            'message': 'Failed to generate upload URL',
        }, origin)

    public_url = f'https://upload.aspph.org/{object_key}'

    return build_response(200, {
        'uploadUrl': upload_url,
        'publicUrl': public_url,
        'objectKey': object_key,
        'expiresIn': 300,
    }, origin)
