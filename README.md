# S3 Upload Portal

Password-protected file upload portal for ASPPH staff. Generates presigned S3 URLs for direct browser-to-S3 uploads, returning permanent public links for use on aspph.org.

**Live at:** https://send.aspph.org

## Architecture

```
Browser (send.aspph.org)
    │
    ├─ POST /v1/upload ──► API Gateway ──► Lambda (presigned URL generation)
    │                                         │
    │                                         ├─ Validates password (Secrets Manager)
    │                                         ├─ Validates file type + size
    │                                         └─ Returns presigned PUT URL
    │
    └─ PUT (file) ──────► S3 (aspph-prod-web-assets/uploads/...)
                              │
                              └─ Returns permanent public URL
```

**Key services:**
- CloudFront + S3 — static frontend hosting
- API Gateway (REST) — upload endpoint with throttling and access logging
- Lambda (Python 3.13) — auth validation, presigned URL generation
- Secrets Manager — upload password storage
- S3 (`aspph-prod-web-assets`) — file storage (public bucket)

## Configuration

| Setting | Location | Current Value |
|---------|----------|---------------|
| Upload password | Secrets Manager: `s3-upload-portal/prod/upload-password` | (secret) |
| Allowed file types | Lambda env var: `ALLOWED_CONTENT_TYPES` | `application/pdf` |
| Upload prefix | Lambda env var: `UPLOAD_PREFIX` | `uploads/` |
| Target bucket | Lambda env var: `TARGET_BUCKET` | `aspph-prod-web-assets` |
| CORS origin | Lambda env var: `ALLOWED_ORIGIN` | `https://send.aspph.org` |

### Changing allowed file types

Update the `AllowedContentTypes` default in `cloudformation/lambda.yaml` and `cloudformation/main.yaml`. Comma-separated MIME types:

```
application/pdf,image/jpeg,image/png
```

Also update the frontend's `ALLOWED_CONTENT_TYPES` set in `src/frontend/app.js` and the `accept` attribute in `src/frontend/index.html` to match.

### Changing the password

Update the secret value in AWS Secrets Manager (`s3-upload-portal/prod/upload-password`). No redeployment needed — the next Lambda cold start picks up the new value.

## Development

### Prerequisites

- Python 3.13+
- AWS CLI configured with appropriate credentials

### Running tests

```bash
pip install -r requirements-test.txt
pytest tests/ -q --tb=short
```

### Project structure

```
cloudformation/
├── main.yaml              # Root stack (orchestrates nested stacks)
├── lambda.yaml            # Lambda function + Secrets Manager + IAM
├── api-gateway.yaml       # REST API with throttling + access logs
└── frontend.yaml          # CloudFront + S3 frontend bucket

src/
├── lambda/handler.py      # Lambda handler (presigned URL generation)
└── frontend/              # Static HTML/CSS/JS served via CloudFront
    ├── index.html
    ├── app.js
    └── style.css

tests/                     # pytest unit + property-based tests
.github/
├── config/prod.json       # Deployment configuration
└── workflows/deploy.yml   # GitHub Actions deployment
```

## Deployment

Deployment is automated via GitHub Actions. Pushing to `main` triggers:

1. **Validate** — CloudFormation template validation
2. **Test** — pytest suite
3. **Deploy** — Package Lambda → upload to S3 → deploy CloudFormation → sync frontend → invalidate CloudFront cache

### Manual deployment

If needed, deploy manually:

```bash
# Package Lambda
mkdir -p build
cp src/lambda/handler.py build/
pip install boto3 -t build/
cd build && zip -r ../lambda.zip . && cd ..

# Upload templates
aws s3 cp cloudformation/ s3://aspph-prod-web-assets/cloudformation/ --recursive

# Deploy stack
aws cloudformation deploy \
  --stack-name s3-upload-portal-prod \
  --template-file cloudformation/main.yaml \
  --capabilities CAPABILITY_NAMED_IAM

# Update Lambda code
aws lambda update-function-code \
  --function-name s3-upload-portal-prod \
  --zip-file fileb://lambda.zip

# Sync frontend
aws s3 sync src/frontend/ s3://$(aws cloudformation describe-stacks \
  --stack-name s3-upload-portal-prod \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
  --output text)/ --delete
```

## Security

- Uploads require a shared password (stored in Secrets Manager, not in code)
- CORS restricted to `https://send.aspph.org` only
- Lambda IAM role scoped to `s3:PutObject` on `aspph-prod-web-assets/uploads/*` only
- Frontend bucket fully private (CloudFront OAC access only)
- API Gateway throttled at 50 burst / 20 sustained requests per second
- TLS 1.2+ enforced on CloudFront
- Presigned upload URLs expire after 5 minutes
- CloudWatch access logging enabled on API Gateway

## DNS

`send.aspph.org` → CNAME to CloudFront distribution domain (uses `*.aspph.org` wildcard ACM cert)
