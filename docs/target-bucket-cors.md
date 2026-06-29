# Target Bucket CORS Configuration

## Overview

The target S3 bucket (e.g. `aspph-prod-web-assets`) is an **existing** bucket that is NOT created or managed by this CloudFormation stack. For presigned PUT uploads from the browser to work, the target bucket must have CORS configured to allow PUT requests from the CloudFront origin.

Without this CORS configuration, browsers will block the direct PUT upload to S3 even though the presigned URL is valid.

## Required CORS Configuration

The CORS rule must allow:
- **Origin**: The CloudFront distribution URL (e.g. `https://d1234567890.cloudfront.net`)
- **Method**: `PUT` (used by the presigned URL upload)
- **Header**: `Content-Type` (set by the frontend during upload)

The configuration template is in `cloudformation/target-bucket-cors.json`. Replace `${AllowedOrigin}` with your actual CloudFront domain before applying.

## Applying the Configuration

### 1. Create a resolved configuration file

Copy `cloudformation/target-bucket-cors.json` and replace `${AllowedOrigin}` with your CloudFront domain:

```json
{
  "CORSRules": [
    {
      "AllowedOrigins": ["https://d1234567890.cloudfront.net"],
      "AllowedMethods": ["PUT"],
      "AllowedHeaders": ["Content-Type"],
      "MaxAgeSeconds": 3600
    }
  ]
}
```

### 2. Apply via AWS CLI

```bash
aws s3api put-bucket-cors \
  --bucket BUCKET_NAME \
  --cors-configuration file://cloudformation/target-bucket-cors.json \
  --no-cli-pager
```

Replace `BUCKET_NAME` with your target bucket name (e.g. `aspph-prod-web-assets`).

### 3. Verify the configuration

```bash
aws s3api get-bucket-cors --bucket BUCKET_NAME --no-cli-pager
```

## Why This Is Needed

The S3 Upload Portal uses a **presigned URL pattern**:

1. The browser requests a presigned PUT URL from the Lambda function
2. The browser then PUTs the file directly to S3 using that presigned URL

Step 2 is a cross-origin request (the page is served from CloudFront, but the PUT goes to `*.s3.amazonaws.com`). Without CORS allowing PUT from the CloudFront origin, the browser will block this request.

## Notes

- `MaxAgeSeconds: 3600` caches the preflight response for 1 hour, reducing OPTIONS requests
- Only `PUT` is allowed — the bucket does not need `GET`, `POST`, or `DELETE` in CORS since public reads don't require CORS and all other operations go through API Gateway
- If you change the CloudFront distribution domain, you must update this CORS configuration
