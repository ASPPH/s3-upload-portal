# S3 Upload Portal

Password-protected file upload portal for ASPPH staff. Generates presigned S3 URLs for direct browser-to-S3 uploads, returning permanent public links for use on aspph.org.

**Live at:** https://s3.aspph.org

## Architecture

```
Browser (s3.aspph.org)
    │
    ├─ POST /v1/upload ──► API Gateway ──► Lambda (presigned URL generation)
    │                                         │
    │                                         ├─ Validates password (Secrets Manager)
    │                                         ├─ Validates file type + size
    │                                         ├─ Sanitizes filename
    │                                         ├─ Checks for existing file (overwrite prompt)
    │                                         └─ Returns presigned PUT URL
    │
    └─ PUT (file) ──────► S3 (aspph-prod-web-assets/shared/...)
                              │
                              └─ Returns permanent public URL
```

**Key services:**
- CloudFront + S3 — static frontend hosting
- API Gateway (REST) — upload endpoint with throttling and access logging
- Lambda (Python 3.13) — auth validation, presigned URL generation
- Secrets Manager — upload password storage
- S3 (`aspph-prod-web-assets`) — file storage (public bucket)

## Features

### Drag-and-drop upload
Users can drag a PDF onto the drop zone or click to browse. Visual feedback (border color change) shows when a file is being dragged over.

### Filename sanitization
Filenames are automatically cleaned for URL safety. The transformation happens server-side in Lambda and is previewed client-side before upload:
- Spaces → hyphens
- Parentheses, brackets, special characters → removed
- Uppercase → lowercase
- Multiple hyphens/underscores → collapsed

Examples:
| Original | Sanitized |
|----------|-----------|
| `ASPPH_Bylaws (1).pdf` | `aspph_bylaws-1.pdf` |
| `Annual Report 2025.pdf` | `annual-report-2025.pdf` |
| `Q1 Budget [FINAL].pdf` | `q1-budget-final.pdf` |

A "File will be saved as:" preview shows the cleaned name before upload.

### Overwrite confirmation
If a file with the same sanitized name already exists in S3, the user gets a confirmation dialog showing the existing URL and asking whether to overwrite.

### Replacing an existing file
To update a file that's already been uploaded (e.g., a new version of a report), simply upload a file with the same name. The system will detect the existing file and prompt you to confirm the overwrite. The public URL stays the same, so any links already shared will automatically point to the new version — no need to update links in emails or on websites.

### Upload history
A "Recent uploads" section below the form shows files uploaded during the current browser session, with clickable links and timestamps. Stored in sessionStorage (clears on tab close). Includes a "Clear history" button.

### Clickable result URL
After upload, the public URL is displayed as a clickable link that opens in a new tab. The Copy button copies it to clipboard with visual confirmation.

### Upload another
After a successful upload, an "Upload another file" button resets the form without refreshing the page.

## Configuration

| Setting | Location | Current Value |
|---------|----------|---------------|
| Upload password | Secrets Manager: `s3-upload-portal/prod/upload-password` | (secret) |
| Allowed file types | Lambda env var: `ALLOWED_CONTENT_TYPES` | `application/pdf` |
| Upload prefix | Lambda env var: `UPLOAD_PREFIX` | `shared/` |
| Target bucket | Lambda env var: `TARGET_BUCKET` | `aspph-prod-web-assets` |
| CORS origin | Lambda env var: `ALLOWED_ORIGIN` | `https://s3.aspph.org` |

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
- CORS restricted to `https://s3.aspph.org` only
- Lambda IAM role scoped to `s3:PutObject` and `s3:GetObject` on `aspph-prod-web-assets/shared/*` only
- Frontend bucket fully private (CloudFront OAC access only)
- API Gateway throttled at 50 burst / 20 sustained requests per second
- TLS 1.2+ enforced on CloudFront
- Presigned upload URLs expire after 5 minutes
- CloudWatch access logging enabled on API Gateway
- Filenames sanitized server-side to prevent path traversal or URL issues

## DNS

`s3.aspph.org` → CNAME to CloudFront distribution domain (uses `*.aspph.org` wildcard ACM cert)

## Contact

Questions or issues: helpdesk@aspph.org
