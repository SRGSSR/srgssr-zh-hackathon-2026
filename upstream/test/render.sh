#!/bin/sh
# Apply the patch to a clean copy of chat.publicai.co and render the LiteLLM config Argo would deploy.
# Usage: upstream/test/render.sh [path-to-chat.publicai.co-clone] [prod|staging]
# Needs: git, helm, ruby (only for YAML plumbing, like the repo's own tooling).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-$HERE/.work/chat.publicai.co}"
ENV="${2:-prod}"
BASE="$(cat "$HERE/../patches/BASE_COMMIT")"
OUT="$HERE/.work/out"
mkdir -p "$HERE/.work" "$OUT"
if [ ! -d "$SRC/.git" ]; then
  git clone --quiet https://github.com/forpublicai/chat.publicai.co.git "$SRC"
fi
WORK="$HERE/.work/patched"
[ -d "$WORK" ] || git clone --quiet "$SRC" "$WORK"
git -C "$WORK" fetch --quiet origin "$BASE" 2>/dev/null || true
git -C "$WORK" checkout --quiet --force "$BASE"
git -C "$WORK" clean --quiet -fd
CHART="$WORK/charts/platform/charts/litellm"
ruby -ryaml -e '
  v = YAML.load_file(ARGV[0]); sub = v.fetch("litellm", {}).dup
  sub["global"] = {"environment" => v["global"]["environment"], "namespace" => "platform"}
  File.write(ARGV[1], sub.to_yaml)' "$WORK/argo/environments/$ENV/platform-values.yaml" "$OUT/values-$ENV.yaml"
# baseline (unpatched) render, to prove the patch changes nothing else
helm template litellm "$CHART" -f "$OUT/values-$ENV.yaml" --show-only templates/configmap.yaml > "$OUT/configmap-$ENV.base.yaml"
ruby -ryaml -e 'File.write(ARGV[1], YAML.load_file(ARGV[0])["data"]["config.yaml"])' "$OUT/configmap-$ENV.base.yaml" "$OUT/config-$ENV.base.yaml"
git -C "$WORK" apply "$HERE/../patches/0001-jurisdiction-metadata-and-policy-hook.patch"
helm template litellm "$CHART" -f "$OUT/values-$ENV.yaml" --set jurisdictionPolicy.enabled=true \
  --show-only templates/configmap.yaml > "$OUT/configmap-$ENV.yaml"
helm template litellm "$CHART" -f "$OUT/values-$ENV.yaml" --set jurisdictionPolicy.enabled=true \
  --show-only templates/deployment.yaml > "$OUT/deployment-$ENV.yaml"
ruby -ryaml -e 'File.write(ARGV[1], YAML.load_file(ARGV[0])["data"]["config.yaml"])' "$OUT/configmap-$ENV.yaml" "$OUT/config-$ENV.yaml"
cp "$CHART/jurisdiction_policy.py" "$OUT/"
echo "rendered $OUT/config-$ENV.yaml ($(grep -c 'jurisdiction:' "$OUT/config-$ENV.yaml") deployments with jurisdiction, image: $(grep 'image:' "$OUT/deployment-$ENV.yaml" | tr -d ' '))"
