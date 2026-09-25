#!/bin/sh
# Deploy or update the demo on Azure. Usage: deploy/azure/deploy.sh [subscription] [resource-group] [location]
# PUBLICAI_API_KEY comes from the environment or the repository's .env. Without one, the VM keeps the key
# it already has; only a new VM (after teardown.sh) needs it once, or it answers with simulated responses.
# DEMO_PASSWORD=... protects the demo with one shared password (user jury); without it the demo is open.
# The demo is served at promisekept.ch (www and the Azure name redirect there). DOMAINS=other.ch,... serves
# other domains (their DNS first); DOMAINS= serves only the Azure name.
# BRANCH=... deploys another branch. Re-run to deploy the branch's latest commit.
set -e
SUB="${1:-z231-as-technology-playground-dev}"; RG="${2:-rg-commune-letter-demo}"; LOCATION="${3:-switzerlandnorth}"
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"

KEY="${PUBLICAI_API_KEY:-}"
if [ -z "$KEY" ] && [ -f "$ROOT/.env" ]; then KEY=$(sed -n 's/^PUBLICAI_API_KEY=//p' "$ROOT/.env" | tail -1); fi
# Azure requires an SSH key even though port 22 stays closed. Keep it: the VM's key cannot change later.
SSH_KEY="$HOME/.ssh/commune-letter-azure"
[ -f "$SSH_KEY.pub" ] || ssh-keygen -q -t ed25519 -N '' -C commune-letter-azure -f "$SSH_KEY"

# Secrets go through a private parameters file, not the command line.
PARAMS=$(mktemp); trap 'rm -f "$PARAMS"' EXIT
KEY="$KEY" LOCATION="$LOCATION" PASS="${DEMO_PASSWORD:-}" BRANCH="${BRANCH:-public-ai-service}" DOMAINS="${DOMAINS-promisekept.ch,www.promisekept.ch}" PUB="$(cat "$SSH_KEY.pub")" python3 -c '
import json, os
p = {"publicAiApiKey": os.environ["KEY"], "demoPassword": os.environ["PASS"], "location": os.environ["LOCATION"],
     "branch": os.environ["BRANCH"], "domains": os.environ["DOMAINS"], "adminPublicKey": os.environ["PUB"]}
print(json.dumps({"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                  "contentVersion": "1.0.0.0", "parameters": {k: {"value": v} for k, v in p.items()}}))' > "$PARAMS"

az account set --subscription "$SUB"
az group show --name "$RG" --output none 2>/dev/null || \
  az group create --name "$RG" --location "$LOCATION" --tags Project=commune-letter-hackathon --output none
az deployment group create --resource-group "$RG" --name commune-letter-demo \
  --template-file "$HERE/main.bicep" --parameters @"$PARAMS" \
  --query 'properties.outputs.url.value' --output tsv
