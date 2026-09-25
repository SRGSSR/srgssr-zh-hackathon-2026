# Runs on the VM as root through the Custom Script extension, on the first deploy and on every
# redeploy. main.bicep prepends REPO_URL, BRANCH, SITE_HOST, DOMAINS, KEY_B64 and PASS_B64.
# Idempotent: installs Docker once, then pulls the branch, writes .env and the Caddy files, restarts.
# The Caddy override lives in /etc/commune-letter, so the deployed branch needs no Azure-specific files.
set -eu
export DEBIAN_FRONTEND=noninteractive
DIR=/opt/commune-letter
CONF=/etc/commune-letter
COMPOSE="docker compose -f docker-compose.yml -f $CONF/compose.azure.yml"

if ! docker compose version >/dev/null 2>&1; then
  apt-get -o DPkg::Lock::Timeout=600 update
  apt-get -o DPkg::Lock::Timeout=600 install -y docker.io docker-compose-v2 docker-buildx git
  systemctl enable --now docker
fi

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$DIR" reset --hard FETCH_HEAD
else
  git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$DIR"
fi
cd "$DIR"

KEY=$(printf %s "$KEY_B64" | base64 -d)
# No key given: keep the one already on the VM, so a redeploy never falls back to simulated answers.
[ -n "$KEY" ] || [ ! -f .env ] || KEY=$(sed -n 's/^PUBLICAI_API_KEY=//p' .env | tail -1)
# Never run without a working key: the demo would quietly answer with simulated responses. Both checks
# stop before .env and the stack are touched, so the demo that is up keeps running as it is.
if [ -z "$KEY" ]; then
  echo "NO_PUBLICAI_KEY: no Public AI API key given and none on the VM; nothing was changed." >&2
  exit 1
fi
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 30 https://api.publicai.co/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -H 'User-Agent: commune-letter-helper/0.1 (hackathon prototype)' \
  -d '{"model":"swiss-ai/apertus-v1.5-70b","messages":[{"role":"user","content":"ok"}],"max_tokens":1}' || true)
case "$CODE" in
  401|403) echo "PUBLICAI_KEY_REJECTED: Public AI answered $CODE to the key; nothing was changed." >&2; exit 1 ;;
  200) echo "Public AI accepted the key." ;;
  *) echo "warning: could not confirm the key (Public AI answered $CODE, it can be slow under load); deploying anyway." ;;
esac
PASS=$(printf %s "$PASS_B64" | base64 -d)
umask 077
mkdir -p "$CONF"
# SIMULATE_WITHOUT_KEY=0: should the key ever go missing, the relay fails instead of faking answers.
printf 'PUBLICAI_API_KEY=%s\nSIMULATE_WITHOUT_KEY=0\n' "$KEY" > .env

# Caddy terminates HTTPS (Let's Encrypt on the VM's cloudapp.azure.com name). Only Caddy is reachable
# from outside; every other service stays bound to 127.0.0.1 or the internal network.
cat > "$CONF/compose.azure.yml" <<EOF
services:
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - $CONF/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
    depends_on: [app]
  app:
    environment:
      SHARED_DEMO: "1"
volumes:
  caddy-data:
EOF
# DOMAINS (optional, comma-separated): the first one serves the demo; the others and the Azure name
# redirect to it. Their DNS must point to this VM before the deploy, or the certificate request fails.
ALL=$(printf '%s,%s' "$DOMAINS" "$SITE_HOST" | tr -d ' ' | tr ',' '\n' | grep -v '^$')
PRIMARY=$(printf '%s\n' "$ALL" | head -1)
OTHERS=$(printf '%s\n' "$ALL" | tail -n +2 | paste -sd, - | sed 's/,/, /g')
AUTH=""
if [ -n "$PASS" ]; then
  HASH=$(docker run --rm caddy:2 caddy hash-password --plaintext "$PASS")
  AUTH=$(printf '  basic_auth {\n    jury %s\n  }' "$HASH")
fi
{
  printf '%s {\n%s\n  reverse_proxy app:8080\n}\n' "$PRIMARY" "$AUTH"
  [ -z "$OTHERS" ] || printf '%s {\n  redir https://%s{uri} permanent\n}\n' "$OTHERS" "$PRIMARY"
} > "$CONF/Caddyfile"
chmod 644 "$CONF/Caddyfile" "$CONF/compose.azure.yml"

$COMPOSE up -d --build --remove-orphans
$COMPOSE restart caddy  # Caddy does not watch its config file
echo "ready: https://$PRIMARY"
