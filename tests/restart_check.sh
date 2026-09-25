#!/bin/sh
# A deferred request survives a gateway restart: it waits in the gateway's store (a volume),
# the worker resumes it after the restart without any client action, and it completes as soon
# as an approved endpoint is back. Runs on the host because it restarts the gateway container.
set -e
KEY="${MUSTERSTADT_API_KEY:-sk-musterstadt-demo}"
GW=http://127.0.0.1:4000
json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
mode() { curl -sf -XPOST "127.0.0.1:$1/control" -H 'Content-Type: application/json' -d "{\"mode\":\"$2\"}" >/dev/null; }
for p in 9100 9101 9102 9103 9104 9105; do curl -sf -XPOST "127.0.0.1:$p/control/reset" >/dev/null; done
for p in 9100 9101 9102; do mode $p down; done

ID=$(curl -sf -XPOST $GW/v1/deferred/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"swiss-ai/apertus-v1.5-70b","messages":[{"role":"user","content":"restart check, fictional data"}]}' | json 'd["id"]')
echo "submitted $ID"
status() { curl -sf "$GW/v1/deferred/jobs?id=$ID" -H "Authorization: Bearer $KEY" | json 'd["status"]'; }
i=0; until [ "$(status)" = waiting ]; do i=$((i+1)); [ $i -gt 90 ] && { echo "FAIL: never waiting"; exit 1; }; sleep 1; done
echo "waiting before restart: ok"

docker compose restart gateway >/dev/null 2>&1
i=0; until curl -sf $GW/health/liveliness >/dev/null 2>&1; do i=$((i+1)); [ $i -gt 90 ] && { echo "FAIL: gateway not back"; exit 1; }; sleep 1; done
S=$(status); echo "after restart: $S"
[ "$S" = waiting ] || [ "$S" = running ] || { echo "FAIL: job lost or ended ($S)"; exit 1; }

mode 9102 up   # only mock-ch-2 comes back; no client calls retry
i=0; until [ "$(status)" = done ]; do i=$((i+1)); [ $i -gt 90 ] && { echo "FAIL: not done after restore"; exit 1; }; sleep 1; done
SERVED=$(curl -sf "$GW/v1/deferred/jobs?id=$ID" -H "Authorization: Bearer $KEY" | json 'd["served_by"]')
[ "$SERVED" = mock-ch-2 ] || { echo "FAIL: served by $SERVED"; exit 1; }
for p in 9103 9104 9105; do
  N=$(curl -sf "127.0.0.1:$p/control" | json 'd["received"]'); [ "$N" = 0 ] || { echo "FAIL: disallowed endpoint on $p received $N"; exit 1; }
done
for p in 9100 9101 9102 9103 9104 9105; do curl -sf -XPOST "127.0.0.1:$p/control/reset" >/dev/null; done
echo "PASS restart check: waited, survived the gateway restart, completed on mock-ch-2, disallowed endpoints received 0"

# Recreate the endpoint containers (their IPs usually change) without restarting the gateway,
# then check that requests still reach the endpoint the gateway names, and only that one.
docker compose up -d --force-recreate ep-publicai ep-ch-1 ep-ch-2 ep-us-1 ep-nometa ep-sg-1 >/dev/null 2>&1
i=0; until curl -sf 127.0.0.1:9101/control >/dev/null 2>&1; do i=$((i+1)); [ $i -gt 60 ] && { echo "FAIL: endpoints not back"; exit 1; }; sleep 1; done
curl -sf -XPOST 127.0.0.1:9100/control -H 'Content-Type: application/json' -d '{"mode":"down"}' >/dev/null
for n in 1 2 3; do
  curl -sf $GW/v1/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d '{"model":"swiss-ai/apertus-v1.5-70b","messages":[{"role":"user","content":"dns check, fictional data"}]}' >/dev/null
done
CH1=$(curl -sf 127.0.0.1:9101/control | json 'd["received"]')
[ "$CH1" = 3 ] || { echo "FAIL: mock-ch-1 received $CH1 of 3 after the endpoints were recreated"; exit 1; }
for p in 9102 9103 9104 9105; do
  N=$(curl -sf "127.0.0.1:$p/control" | json 'd["received"]'); [ "$N" = 0 ] || { echo "FAIL: port $p received $N after recreate"; exit 1; }
done
for p in 9100 9101 9102 9103 9104 9105; do curl -sf -XPOST "127.0.0.1:$p/control/reset" >/dev/null; done
echo "PASS recreate check: after new endpoint containers, requests reached exactly the endpoint the gateway named"
