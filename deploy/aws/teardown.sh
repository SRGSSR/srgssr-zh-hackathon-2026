#!/bin/sh
# Remove everything the demo created: both secrets (no recovery window), then the whole stack
# (instance, disk, VPC, security group, role). Usage: deploy/aws/teardown.sh [profile] [region]
set -e
PROFILE="${1:-rsi-dev}"; REGION="${2:-eu-central-1}"; STACK=commune-letter-demo
for s in commune-letter-demo/publicai-api-key commune-letter-demo/jury-password; do
  aws secretsmanager delete-secret --profile "$PROFILE" --region "$REGION" --secret-id "$s" \
    --force-delete-without-recovery >/dev/null 2>&1 || true
done
aws cloudformation delete-stack --profile "$PROFILE" --region "$REGION" --stack-name "$STACK"
aws cloudformation wait stack-delete-complete --profile "$PROFILE" --region "$REGION" --stack-name "$STACK"
echo "removed: stack $STACK in $REGION"
