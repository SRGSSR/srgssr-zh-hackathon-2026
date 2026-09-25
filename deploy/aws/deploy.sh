#!/bin/sh
# Deploy the demo stack. Usage: deploy/aws/deploy.sh [profile] [region]
set -e
PROFILE="${1:-rsi-dev}"; REGION="${2:-eu-central-1}"; STACK=commune-letter-demo
HERE="$(cd "$(dirname "$0")" && pwd)"
aws cloudformation deploy --profile "$PROFILE" --region "$REGION" --stack-name "$STACK" \
  --template-file "$HERE/demo.yaml" --capabilities CAPABILITY_IAM \
  --tags Project=commune-letter-hackathon
aws cloudformation describe-stacks --profile "$PROFILE" --region "$REGION" --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
