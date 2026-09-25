#!/bin/sh
# Re-read the jury password from Secrets Manager (on the instance, so it never leaves AWS) and serve
# the demo under a short hex name as well (e.g. 0a000001.sslip.io instead of 10-0-0-1.sslip.io).
# Run it after changing the password secret. Usage: deploy/aws/refresh-caddy.sh [profile] [region]
# NO_AUTH=1 serves the demo without a password (the app then hides the letters list and limits
# letters per address, because SHARED_DEMO=1).
set -e
PROFILE="${1:-rsi-dev}"; REGION="${2:-eu-central-1}"; STACK=commune-letter-demo
ID=$(aws cloudformation describe-stacks --profile "$PROFILE" --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)
IP=$(aws ec2 describe-instances --profile "$PROFILE" --region "$REGION" --instance-ids "$ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
HEX=$(printf '%02x%02x%02x%02x' $(echo "$IP" | tr . ' '))
DASHED=$(echo "$IP" | tr . -)
PARAMS=$(python3 - "$REGION" "$HEX" "$DASHED" "${NO_AUTH:-0}" <<'PY'
import json, sys
region, hexh, dashed, no_auth = sys.argv[1:]
cmds = [
    "set -e",
    "cd /opt/commune-letter",
    f"PASS=$(aws secretsmanager get-secret-value --region {region} --secret-id commune-letter-demo/jury-password --query SecretString --output text)",
    'HASH=$(docker run --rm caddy:2 caddy hash-password --plaintext "$PASS")',
    "umask 077",
    (f"printf '%s, %s {{\\n  reverse_proxy app:8080\\n}}\\n' {hexh}.sslip.io {dashed}.sslip.io > deploy/aws/Caddyfile"
     if no_auth == "1" else
     f"printf '%s, %s {{\\n  basic_auth {{\\n    jury %s\\n  }}\\n  reverse_proxy app:8080\\n}}\\n' {hexh}.sslip.io {dashed}.sslip.io \"$HASH\" > deploy/aws/Caddyfile"),
    "docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml restart caddy",
    "echo refreshed",
]
print(json.dumps({"commands": cmds}))
PY
)
CID=$(aws ssm send-command --profile "$PROFILE" --region "$REGION" --instance-ids "$ID" \
  --document-name AWS-RunShellScript --parameters "$PARAMS" --query Command.CommandId --output text)
sleep 10
aws ssm get-command-invocation --profile "$PROFILE" --region "$REGION" --command-id "$CID" --instance-id "$ID" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' --output text | tail -4
echo "demo: https://$HEX.sslip.io  (also https://$DASHED.sslip.io)"
