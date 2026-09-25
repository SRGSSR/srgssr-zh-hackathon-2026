#!/bin/sh
# Deploy or update the demo on Azure. Usage: deploy/azure/deploy.sh [subscription] [resource-group] [location]
# PUBLICAI_API_KEY comes from the environment or the repository's .env. Without one, the VM keeps the key
# it already has. The deploy refuses, loudly, when there is no key at all or Public AI rejects it: the
# demo would otherwise quietly answer with simulated responses.
# DEMO_PASSWORD=... protects the demo with one shared password (user jury); without it the demo is open.
# The demo is served at promisekept.ch (www and the Azure name redirect there). DOMAINS=other.ch,... serves
# other domains (their DNS first); DOMAINS= serves only the Azure name.
# BRANCH=... deploys another branch. Re-run to deploy the branch's latest commit.
set -e
SUB="${1:-z231-as-technology-playground-dev}"; RG="${2:-rg-commune-letter-demo}"; LOCATION="${3:-switzerlandnorth}"
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"

refuse() {  # $1: headline, $2: explanation. Big and red, so nobody misses it.
  R=$(printf '\033[1;97;41m'); N=$(printf '\033[0m'); BAR="                                                            "
  printf '\n%s%s%s\n%s   NOT DEPLOYED: %-43s%s\n%s%s%s\n\n%s\n\n' "$R" "$BAR" "$N" "$R" "$1" "$N" "$R" "$BAR" "$N" "$2" >&2
  exit 1
}
HOWTO="Pass the key:  PUBLICAI_API_KEY=zpka_... deploy/azure/deploy.sh
or add the line PUBLICAI_API_KEY=... to $ROOT/.env (gitignored)."

KEY="${PUBLICAI_API_KEY:-}"
if [ -z "$KEY" ] && [ -f "$ROOT/.env" ]; then KEY=$(sed -n 's/^PUBLICAI_API_KEY=//p' "$ROOT/.env" | tail -1); fi

az account set --subscription "$SUB"
if [ -z "$KEY" ]; then
  az vm show --resource-group "$RG" --name commune-letter-demo --output none 2>/dev/null ||
    refuse "NO PUBLIC AI API KEY" "There is no VM yet that could keep a key, and none was given.
Without a key the demo would quietly answer with simulated responses.
$HOWTO"
  echo "No key given: the VM keeps its Public AI key (the deploy stops if it has none)."
fi

# Azure requires an SSH key even though port 22 stays closed. Keep it: the VM's key cannot change later.
SSH_KEY="$HOME/.ssh/commune-letter-azure"
[ -f "$SSH_KEY.pub" ] || ssh-keygen -q -t ed25519 -N '' -C commune-letter-azure -f "$SSH_KEY"

# Secrets go through a private parameters file, not the command line.
PARAMS=$(mktemp); ERR=$(mktemp); trap 'rm -f "$PARAMS" "$ERR"' EXIT
KEY="$KEY" LOCATION="$LOCATION" PASS="${DEMO_PASSWORD:-}" BRANCH="${BRANCH:-public-ai-service}" DOMAINS="${DOMAINS-promisekept.ch,www.promisekept.ch}" PUB="$(cat "$SSH_KEY.pub")" python3 -c '
import json, os
p = {"publicAiApiKey": os.environ["KEY"], "demoPassword": os.environ["PASS"], "location": os.environ["LOCATION"],
     "branch": os.environ["BRANCH"], "domains": os.environ["DOMAINS"], "adminPublicKey": os.environ["PUB"]}
print(json.dumps({"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                  "contentVersion": "1.0.0.0", "parameters": {k: {"value": v} for k, v in p.items()}}))' > "$PARAMS"

az group show --name "$RG" --output none 2>/dev/null || \
  az group create --name "$RG" --location "$LOCATION" --tags Project=commune-letter-hackathon --output none
if URL=$(az deployment group create --resource-group "$RG" --name commune-letter-demo \
    --template-file "$HERE/main.bicep" --parameters @"$PARAMS" \
    --query 'properties.outputs.url.value' --output tsv 2>"$ERR"); then
  grep -v adminusername-should-not-be-literal "$ERR" | grep . >&2 || true
  echo "$URL"
else
  # setup.sh stops on the VM, before touching the running demo, and says why.
  grep -q NO_PUBLICAI_KEY "$ERR" && refuse "NO PUBLIC AI API KEY" "None was given and the VM has none either; the running demo was not changed.
$HOWTO"
  grep -q PUBLICAI_KEY_REJECTED "$ERR" && refuse "PUBLIC AI REJECTED THE KEY" "Public AI answered 401/403 to it; the running demo was not changed.
Check or rotate the key, then pass the new one.
$HOWTO"
  cat "$ERR" >&2
  exit 1
fi
