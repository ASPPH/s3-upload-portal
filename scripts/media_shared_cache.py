"""Give media.aspph.org/shared/* a short cache so replaced PDFs show up within minutes.

media.aspph.org (CloudFront E1MM5V1CVFO6YD) caches everything for 24 hours by
default. When someone replaces a file through the upload portal, the link keeps
serving the old copy until that cache expires. This script:

  1. saves a backup of the distribution config,
  2. creates (or reuses) a cache policy with a 5-minute default TTL,
  3. adds a `shared/*` behavior using it, ahead of the `*` behavior so it matches.

Dry run by default: it prints what it would change and touches nothing.
Pass --apply to make the change.

    python scripts/media_shared_cache.py --profile Prod
    python scripts/media_shared_cache.py --profile Prod --apply

Rollback: aws cloudfront update-distribution --id E1MM5V1CVFO6YD \
  --distribution-config file://<backup>.config.json --if-match <current ETag>
"""

import argparse
import copy
import datetime
import json
import subprocess
import sys

DISTRIBUTION_ID = 'E1MM5V1CVFO6YD'
PATH_PATTERN = 'shared/*'
ORIGIN_ID = 'aspph-prod-web-assets.s3.us-east-1.amazonaws.com'
POLICY_NAME = 'media-aspph-shared-5min'
DEFAULT_TTL = 300
MAX_TTL = 3600


def aws(profile, *args):
    cmd = ['aws', *args, '--profile', profile, '--output', 'json']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f'aws {" ".join(args[:2])} failed:\n{result.stderr}')
    return json.loads(result.stdout) if result.stdout.strip() else {}


def find_policy(profile):
    policies = aws(profile, 'cloudfront', 'list-cache-policies', '--type', 'custom')
    for item in policies.get('CachePolicyList', {}).get('Items', []):
        if item['CachePolicy']['CachePolicyConfig']['Name'] == POLICY_NAME:
            return item['CachePolicy']['Id']
    return None


def create_policy(profile):
    config = {
        'Name': POLICY_NAME,
        'Comment': 'Upload portal PDFs on media.aspph.org: 5 min default so replaced files refresh quickly',
        'DefaultTTL': DEFAULT_TTL,
        'MaxTTL': MAX_TTL,
        'MinTTL': 0,
        'ParametersInCacheKeyAndForwardedToOrigin': {
            'EnableAcceptEncodingGzip': True,
            'EnableAcceptEncodingBrotli': True,
            'HeadersConfig': {'HeaderBehavior': 'none'},
            'CookiesConfig': {'CookieBehavior': 'none'},
            'QueryStringsConfig': {'QueryStringBehavior': 'none'},
        },
    }
    created = aws(profile, 'cloudfront', 'create-cache-policy',
                  '--cache-policy-config', json.dumps(config))
    return created['CachePolicy']['Id']


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--profile', default='Prod')
    parser.add_argument('--apply', action='store_true', help='make the change (default: dry run)')
    args = parser.parse_args()

    current = aws(args.profile, 'cloudfront', 'get-distribution-config', '--id', DISTRIBUTION_ID)
    etag = current['ETag']
    config = current['DistributionConfig']
    behaviors = config['CacheBehaviors'].get('Items', [])

    print(f'Distribution {DISTRIBUTION_ID} (ETag {etag}), current behaviors in order:')
    for b in behaviors:
        print(f'  {b["PathPattern"]:24} -> {b["TargetOriginId"]}  cache policy {b.get("CachePolicyId")}')

    if any(b['PathPattern'] == PATH_PATTERN for b in behaviors):
        sys.exit(f'A {PATH_PATTERN} behavior already exists. Nothing to do.')

    template = next((b for b in behaviors if b['PathPattern'] == '*' and b['TargetOriginId'] == ORIGIN_ID), None)
    if template is None:
        sys.exit(f'Could not find the * behavior for {ORIGIN_ID} to copy settings from. Stopping.')

    policy_id = find_policy(args.profile)
    print(f'\nCache policy {POLICY_NAME}: ' + (f'exists ({policy_id})' if policy_id else
          f'will be created (default {DEFAULT_TTL}s, max {MAX_TTL}s)'))
    print(f'Will add {PATH_PATTERN} -> {ORIGIN_ID} as behavior #1, same settings as * except the cache policy.')

    if not args.apply:
        print('\nDry run only. Re-run with --apply to make the change.')
        return

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = f'{DISTRIBUTION_ID}-backup-{stamp}'
    with open(f'{backup}.full.json', 'w') as f:
        json.dump(current, f, indent=2)
    with open(f'{backup}.config.json', 'w') as f:
        json.dump(config, f, indent=2)
    print(f'\nBacked up config to {backup}.config.json (ETag {etag})')

    if not policy_id:
        policy_id = create_policy(args.profile)
        print(f'Created cache policy {POLICY_NAME}: {policy_id}')

    new_behavior = copy.deepcopy(template)
    new_behavior['PathPattern'] = PATH_PATTERN
    new_behavior['CachePolicyId'] = policy_id

    config['CacheBehaviors']['Items'] = [new_behavior] + behaviors
    config['CacheBehaviors']['Quantity'] = len(config['CacheBehaviors']['Items'])

    new_config_file = f'{DISTRIBUTION_ID}-new-{stamp}.json'
    with open(new_config_file, 'w') as f:
        json.dump(config, f, indent=2)

    updated = aws(args.profile, 'cloudfront', 'update-distribution', '--id', DISTRIBUTION_ID,
                  '--distribution-config', f'file://{new_config_file}', '--if-match', etag)
    print(f'Updated. Status: {updated["Distribution"]["Status"]} (takes a few minutes to deploy).')
    print(f'Check: aws cloudfront get-distribution --id {DISTRIBUTION_ID} --profile {args.profile} '
          '--query Distribution.Status')


if __name__ == '__main__':
    main()
