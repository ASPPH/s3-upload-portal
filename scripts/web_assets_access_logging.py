"""Turn on S3 server access logging for aspph-prod-web-assets.

Before we remove the AllowPublicRead statement from aspph-prod-web-assets we
need to know who still fetches files straight from the bucket
(https://aspph-prod-web-assets.s3.amazonaws.com/...) instead of through
media.aspph.org. S3 server access logs record every request, including
anonymous ones. This script:

  1. saves a backup of the bucket's current logging config and the log
     bucket's lifecycle rules,
  2. checks that the existing log bucket aspph-s3-accesslogs is private, in the
     same region, and lets the S3 logging service write to it,
  3. adds a lifecycle rule to aspph-s3-accesslogs that deletes these logs
     (and only these: prefix aspph-prod-web-assets/) after 60 days,
  4. turns on logging into aspph-s3-accesslogs under that prefix, with
     date-partitioned keys so Athena can read them by day.

Logs from aspph-meetings and data-center-prod-assets already go to the same
bucket (at its root) and are not touched.

Dry run by default: it prints what it would change and touches nothing.
Pass --apply to make the change.

    python scripts/web_assets_access_logging.py --profile Prod
    python scripts/web_assets_access_logging.py --profile Prod --apply

Rollback (stop logging; existing log files stay until the lifecycle rule
deletes them):
    aws s3api put-bucket-logging --bucket aspph-prod-web-assets \
      --bucket-logging-status "{}" --profile Prod
To also remove the 60-day rule, restore the lifecycle backup this script saves:
    aws s3api put-bucket-lifecycle-configuration --bucket aspph-s3-accesslogs \
      --lifecycle-configuration file://<backup>.lifecycle.json --profile Prod
"""

import argparse
import datetime
import json
import subprocess
import sys

SOURCE_BUCKET = 'aspph-prod-web-assets'
LOG_BUCKET = 'aspph-s3-accesslogs'
LOG_PREFIX = f'{SOURCE_BUCKET}/'
RULE_ID = f'expire-{SOURCE_BUCKET}-access-logs-60d'
EXPIRE_DAYS = 60


def aws(profile, *args, allow_missing=None):
    cmd = ['aws', *args, '--profile', profile, '--output', 'json']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if allow_missing and allow_missing in result.stderr:
            return None
        sys.exit(f'aws {" ".join(args[:2])} failed:\n{result.stderr}')
    return json.loads(result.stdout) if result.stdout.strip() else {}


def check_log_bucket(profile):
    """Stop if the log bucket isn't a safe, working place for the logs."""
    problems = []

    region = aws(profile, 's3api', 'get-bucket-location', '--bucket', LOG_BUCKET)['LocationConstraint']
    source_region = aws(profile, 's3api', 'get-bucket-location', '--bucket', SOURCE_BUCKET)['LocationConstraint']
    if region != source_region:
        problems.append(f'log bucket region {region or "us-east-1"} != source region {source_region or "us-east-1"}')

    pab = aws(profile, 's3api', 'get-public-access-block', '--bucket', LOG_BUCKET,
              allow_missing='NoSuchPublicAccessBlockConfiguration')
    if not pab or not all(pab['PublicAccessBlockConfiguration'].values()):
        problems.append('Block Public Access is not fully on')

    policy = aws(profile, 's3api', 'get-bucket-policy', '--bucket', LOG_BUCKET, allow_missing='NoSuchBucketPolicy')
    statements = json.loads(policy['Policy'])['Statement'] if policy else []
    if not any(s.get('Effect') == 'Allow'
               and s.get('Principal', {}).get('Service') == 'logging.s3.amazonaws.com'
               and 's3:PutObject' in (s['Action'] if isinstance(s['Action'], list) else [s['Action']])
               and f'arn:aws:s3:::{LOG_BUCKET}/*' in (s['Resource'] if isinstance(s['Resource'], list) else [s['Resource']])
               and 'Condition' not in s  # a conditioned statement may not cover this source bucket
               for s in statements):
        problems.append('bucket policy has no unconditional Allow for logging.s3.amazonaws.com s3:PutObject')

    if problems:
        sys.exit(f'{LOG_BUCKET} is not ready:\n  - ' + '\n  - '.join(problems))
    print(f'{LOG_BUCKET}: same region, Block Public Access on, logging service allowed to write. OK')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--profile', default='Prod')
    parser.add_argument('--apply', action='store_true', help='make the change (default: dry run)')
    args = parser.parse_args()

    account = aws(args.profile, 'sts', 'get-caller-identity')['Account']
    current_logging = aws(args.profile, 's3api', 'get-bucket-logging', '--bucket', SOURCE_BUCKET)
    print(f'Account {account}. Current logging on {SOURCE_BUCKET}: '
          + (json.dumps(current_logging['LoggingEnabled']) if current_logging.get('LoggingEnabled') else 'off'))

    check_log_bucket(args.profile)

    lifecycle = aws(args.profile, 's3api', 'get-bucket-lifecycle-configuration', '--bucket', LOG_BUCKET,
                    allow_missing='NoSuchLifecycleConfiguration') or {'Rules': []}
    rules = lifecycle['Rules']
    print(f'\nLifecycle rules on {LOG_BUCKET} now: ' + (', '.join(r['ID'] for r in rules) or 'none'))
    add_rule = not any(r['ID'] == RULE_ID for r in rules)
    print(f'Will add rule {RULE_ID}: delete objects under {LOG_PREFIX} after {EXPIRE_DAYS} days. Other rules unchanged.'
          if add_rule else f'Rule {RULE_ID} already exists. Leaving lifecycle alone.')

    logging_status = {
        'LoggingEnabled': {
            'TargetBucket': LOG_BUCKET,
            'TargetPrefix': LOG_PREFIX,
            'TargetObjectKeyFormat': {'PartitionedPrefix': {'PartitionDateSource': 'EventTime'}},
        }
    }
    print(f'Will turn on logging: {SOURCE_BUCKET} -> s3://{LOG_BUCKET}/{LOG_PREFIX}'
          f'{account}/us-east-1/{SOURCE_BUCKET}/YYYY/MM/DD/...')

    if not args.apply:
        print('\nDry run only. Re-run with --apply to make the change.')
        return

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = f'{SOURCE_BUCKET}-logging-backup-{stamp}'
    with open(f'{backup}.logging.json', 'w') as f:
        json.dump(current_logging, f, indent=2)
    lifecycle_backup = {'Rules': rules}
    with open(f'{backup}.lifecycle.json', 'w') as f:
        json.dump(lifecycle_backup, f, indent=2)
    print(f'\nBacked up to {backup}.logging.json and {backup}.lifecycle.json')

    if add_rule:
        new_rules = rules + [{
            'ID': RULE_ID,
            'Filter': {'Prefix': LOG_PREFIX},
            'Status': 'Enabled',
            'Expiration': {'Days': EXPIRE_DAYS},
        }]
        lifecycle_args = ['s3api', 'put-bucket-lifecycle-configuration', '--bucket', LOG_BUCKET,
                          '--lifecycle-configuration', json.dumps({'Rules': new_rules})]
        # Returned alongside the rules by get-; put- takes it as its own flag.
        if 'TransitionDefaultMinimumObjectSize' in lifecycle:
            lifecycle_args += ['--transition-default-minimum-object-size',
                               lifecycle['TransitionDefaultMinimumObjectSize']]
        aws(args.profile, *lifecycle_args)
        print(f'Added lifecycle rule {RULE_ID}.')

    aws(args.profile, 's3api', 'put-bucket-logging', '--bucket', SOURCE_BUCKET,
        '--bucket-logging-status', json.dumps(logging_status))
    print(f'Logging is on. First log files usually appear within an hour. Check:')
    print(f'  aws s3 ls s3://{LOG_BUCKET}/{LOG_PREFIX} --recursive --profile {args.profile} | head')


if __name__ == '__main__':
    main()
