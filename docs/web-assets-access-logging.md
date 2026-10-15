# Access logging on aspph-prod-web-assets

Step 2 of closing public S3 access on `aspph-prod-web-assets` (Prod, account 896338196417).
We log every request to the bucket for a few weeks so we can find links that still point
straight at S3 (`https://aspph-prod-web-assets.s3.amazonaws.com/...`) before we remove the
`AllowPublicRead` policy statement and turn on Block Public Access.

## What gets changed

Checked read-only on 2026-10-14:

| | Before | After |
|---|---|---|
| Logging on `aspph-prod-web-assets` | off | on, to `s3://aspph-s3-accesslogs/aspph-prod-web-assets/` |
| Lifecycle on `aspph-s3-accesslogs` | `WAR-abort-mpu-7d` only | same, plus `expire-aspph-prod-web-assets-access-logs-60d` (deletes objects under `aspph-prod-web-assets/` after 60 days) |

No new bucket. `aspph-s3-accesslogs` already exists and already receives logs from
`aspph-meetings` and `data-center-prod-assets`. It is private (Block Public Access fully on,
bucket owner enforced, SSE-S3) and its bucket policy already lets `logging.s3.amazonaws.com`
write to it, so no policy change is needed. The new 60-day rule only matches the new prefix;
the other buckets' logs (at the bucket root, kept since 2023) are not affected.

Log files land under date folders:
`aspph-prod-web-assets/896338196417/us-east-1/aspph-prod-web-assets/YYYY/MM/DD/`.
That layout is what the Athena table expects.

No change to `aspph-prod-web-assets`'s bucket policy, so GuardDuty's
`Policy:S3/BucketPublicAccessGranted` finding should not fire for this step.

## Run it

```bash
aws sso login --profile Prod
```

Dry run (reads only, prints the plan):

```bash
python scripts/web_assets_access_logging.py --profile Prod
```

Apply:

```bash
python scripts/web_assets_access_logging.py --profile Prod --apply
```

`--apply` first writes two backup files in the current folder,
`aspph-prod-web-assets-logging-backup-<timestamp>.logging.json` and `.lifecycle.json`, then
adds the lifecycle rule, then turns on logging. Keep the backups until the project is closed.

If you'd rather run plain CLI commands, these are the equivalent:

```bash
aws s3api get-bucket-logging --bucket aspph-prod-web-assets --profile Prod > web-assets-logging-backup.json
```

```bash
aws s3api get-bucket-lifecycle-configuration --bucket aspph-s3-accesslogs --profile Prod > accesslogs-lifecycle-backup.json
```

```bash
aws s3api put-bucket-lifecycle-configuration --bucket aspph-s3-accesslogs --profile Prod --transition-default-minimum-object-size all_storage_classes_128K --lifecycle-configuration "{\"Rules\":[{\"ID\":\"WAR-abort-mpu-7d\",\"Filter\":{\"Prefix\":\"\"},\"Status\":\"Enabled\",\"AbortIncompleteMultipartUpload\":{\"DaysAfterInitiation\":7}},{\"ID\":\"expire-aspph-prod-web-assets-access-logs-60d\",\"Filter\":{\"Prefix\":\"aspph-prod-web-assets/\"},\"Status\":\"Enabled\",\"Expiration\":{\"Days\":60}}]}"
```

```bash
aws s3api put-bucket-logging --bucket aspph-prod-web-assets --profile Prod --bucket-logging-status "{\"LoggingEnabled\":{\"TargetBucket\":\"aspph-s3-accesslogs\",\"TargetPrefix\":\"aspph-prod-web-assets/\",\"TargetObjectKeyFormat\":{\"PartitionedPrefix\":{\"PartitionDateSource\":\"EventTime\"}}}}"
```

(`put-bucket-lifecycle-configuration` replaces the whole rule list, which is why the existing
`WAR-abort-mpu-7d` rule is repeated. The script reads the current rules and does this for you.)

## Check it worked

Logs are delivered on a best-effort basis, usually within an hour:

```bash
aws s3 ls s3://aspph-s3-accesslogs/aspph-prod-web-assets/ --recursive --profile Prod
```

## Rollback

Turn logging off (it was off before; nothing else on the source bucket changes):

```bash
aws s3api put-bucket-logging --bucket aspph-prod-web-assets --bucket-logging-status "{}" --profile Prod
```

Optionally remove the 60-day rule by restoring the lifecycle backup:

```bash
aws s3api put-bucket-lifecycle-configuration --bucket aspph-s3-accesslogs --profile Prod --transition-default-minimum-object-size all_storage_classes_128K --lifecycle-configuration file://aspph-prod-web-assets-logging-backup-<timestamp>.lifecycle.json
```

Leaving the rule in place after rollback is harmless: it just cleans up the logs already written.

## After a couple of weeks: find the direct hits

Open [scripts/web_assets_direct_hits.sql](../scripts/web_assets_direct_hits.sql) and run its
statements one at a time in the Athena console (Prod, us-east-1, workgroup `primary`):

1. `CREATE EXTERNAL TABLE` once. It only adds a table definition to the Glue catalog
   (`default` database); new days appear automatically.
2. Sanity check: who reads the bucket. CloudFront (OAC) and the upload portal role should
   dominate.
3. Direct hits by referrer: the list of web pages whose links need changing to
   `media.aspph.org`.
4. Direct hits in detail: file, referrer, user agent, URL style (`endpoint`), status.
   Download as CSV from the console to share.
5. Same as 4 without obvious crawlers.

"Direct hit" means `requester = '-'` (an anonymous request) for a GET/HEAD of an object.
Both CloudFront distributions that read this bucket (E1MM5V1CVFO6YD = media.aspph.org, and
E7OQDUOH288CA, which has no custom domain) use OAC, so their requests are signed and are
never `'-'`. Anything anonymous will start getting 403 once `AllowPublicRead` is removed.

Cost: S3 charges only for storing the log files (small, deleted after 60 days). Athena
charges per data scanned; with daily partitions and a few weeks of logs, expect cents.

## Follow-up (optional, not part of this step)

The logging-service statement in `aspph-s3-accesslogs`'s bucket policy (console-generated in
2023) has no `aws:SourceAccount` condition. AWS recommends adding one so only this account's
buckets can deliver logs there. That touches logging for the other two buckets too, so it's
left as a separate change.
