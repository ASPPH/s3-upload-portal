-- Find requests that hit aspph-prod-web-assets directly instead of through media.aspph.org.
--
-- Run in the Athena console (Prod, us-east-1, workgroup "primary"), one statement at a time.
-- Needs logging turned on first: scripts/web_assets_access_logging.py --apply
--
-- media.aspph.org (E1MM5V1CVFO6YD) and E7OQDUOH288CA read the bucket with OAC, so their
-- requests are signed and never show requester '-'. Anonymous ('-') GET/HEAD requests are
-- the old public links that will break once AllowPublicRead is removed.

-- 1. Table (one-time). Partition projection means no crawler or MSCK REPAIR is needed:
--    new days show up automatically. Creating it only writes Glue catalog metadata.
CREATE EXTERNAL TABLE IF NOT EXISTS default.aspph_prod_web_assets_access_logs (
  bucketowner STRING,
  bucket_name STRING,
  requestdatetime STRING,
  remoteip STRING,
  requester STRING,
  requestid STRING,
  operation STRING,
  key STRING,
  request_uri STRING,
  httpstatus STRING,
  errorcode STRING,
  bytessent STRING,
  objectsize STRING,
  totaltime STRING,
  turnaroundtime STRING,
  referrer STRING,
  useragent STRING,
  versionid STRING,
  hostid STRING,
  sigv STRING,
  ciphersuite STRING,
  authtype STRING,
  endpoint STRING,
  tlsversion STRING,
  accesspointarn STRING,
  aclrequired STRING,
  sourceregion STRING
)
PARTITIONED BY (`timestamp` STRING)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.RegexSerDe'
WITH SERDEPROPERTIES (
  'input.regex' = '([^ ]*) ([^ ]*) \\[(.*?)\\] ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) (\"[^\"]*\"|-) (-|[0-9]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) (\"[^\"]*\"|-) (\"[^\"]*\"|-) ([^ ]*)(?: ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*))?.*$'
)
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION 's3://aspph-s3-accesslogs/aspph-prod-web-assets/896338196417/us-east-1/aspph-prod-web-assets/'
TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.timestamp.type' = 'date',
  'projection.timestamp.format' = 'yyyy/MM/dd',
  'projection.timestamp.range' = '2026/10/01,NOW',
  'projection.timestamp.interval' = '1',
  'projection.timestamp.interval.unit' = 'DAYS',
  'storage.location.template' = 's3://aspph-s3-accesslogs/aspph-prod-web-assets/896338196417/us-east-1/aspph-prod-web-assets/${timestamp}'
);

-- 2. Sanity check: who is reading the bucket at all. Expect CloudFront/OAC rows, the
--    upload portal's role (PUTs), and hopefully only a few '-' (anonymous) rows.
SELECT requester, useragent, operation, count(*) AS requests
FROM default.aspph_prod_web_assets_access_logs
WHERE "timestamp" >= '2026/10/15'
GROUP BY 1, 2, 3
ORDER BY requests DESC
LIMIT 50;

-- 3. Which web pages still link straight to the bucket. This is the fix-it list:
--    each referrer is a page whose links should be changed to media.aspph.org.
--    Referrer '-' means no referring page (email, PDF, bookmark, app, or a bot).
SELECT referrer,
       count(*) AS requests,
       count(DISTINCT key) AS files,
       min("timestamp") AS first_day,
       max("timestamp") AS last_day
FROM default.aspph_prod_web_assets_access_logs
WHERE "timestamp" >= '2026/10/15'
  AND requester = '-'
  AND operation IN ('REST.GET.OBJECT', 'REST.HEAD.OBJECT')
GROUP BY 1
ORDER BY requests DESC;

-- 4. Full detail of direct hits: file, where the link was, who asked, and which URL style
--    (endpoint = aspph-prod-web-assets.s3.amazonaws.com, or s3.us-east-1.amazonaws.com for
--    path-style links). Export to CSV from the console to share.
SELECT key,
       referrer,
       useragent,
       endpoint,
       httpstatus,
       count(*) AS requests,
       count(DISTINCT remoteip) AS distinct_ips,
       min("timestamp") AS first_day,
       max("timestamp") AS last_day
FROM default.aspph_prod_web_assets_access_logs
WHERE "timestamp" >= '2026/10/15'
  AND requester = '-'
  AND operation IN ('REST.GET.OBJECT', 'REST.HEAD.OBJECT')
GROUP BY 1, 2, 3, 4, 5
ORDER BY requests DESC
LIMIT 1000;

-- 5. Same, with likely crawlers removed (they will just reindex the media.aspph.org links).
SELECT key, referrer, count(*) AS requests, max("timestamp") AS last_day
FROM default.aspph_prod_web_assets_access_logs
WHERE "timestamp" >= '2026/10/15'
  AND requester = '-'
  AND operation IN ('REST.GET.OBJECT', 'REST.HEAD.OBJECT')
  AND NOT regexp_like(lower(useragent), 'bot|crawl|spider|slurp|facebookexternalhit|preview')
GROUP BY 1, 2
ORDER BY requests DESC
LIMIT 1000;

-- Cleanup when the project is done (only removes the table definition, not the logs):
-- DROP TABLE default.aspph_prod_web_assets_access_logs;
