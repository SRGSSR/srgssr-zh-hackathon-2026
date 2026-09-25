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
PASS=$(printf %s "$PASS_B64" | base64 -d)
umask 077
mkdir -p "$CONF"
printf 'PUBLICAI_API_KEY=%s\nSIMULATE_WITHOUT_KEY=1\n' "$KEY" > .env

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
