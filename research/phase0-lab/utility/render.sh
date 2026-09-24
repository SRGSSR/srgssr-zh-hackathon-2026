#!/bin/sh
# Render the Utility's LiteLLM subchart ConfigMap + Deployment for prod and staging (read-only on the clone).
# Mirrors Argo: charts/platform/values.yaml global.* + argo/environments/<env>/platform-values.yaml (litellm: subtree).
# Output: rendered/config-<env>.yaml (the exact config.yaml LiteLLM loads), rendered/deployment-<env>.yaml
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
export DOCKER_CONFIG="$HERE/.helmtmp"; mkdir -p "$DOCKER_CONFIG"
export HELM_REGISTRY_CONFIG="$DOCKER_CONFIG/reg.json" HELM_CACHE_HOME="$DOCKER_CONFIG/c" HELM_CONFIG_HOME="$DOCKER_CONFIG/cfg" HELM_DATA_HOME="$DOCKER_CONFIG/d"
REPO="$HERE/../../chat.publicai.co"
CHART="$REPO/charts/platform/charts/litellm"
mkdir -p "$HERE/rendered"
helm version --short
for ENV in prod staging; do
  # Argo passes the litellm: subtree of argo/environments/$ENV/platform-values.yaml to this subchart,
  # and global.* from both charts/platform/values.yaml and the env file.
  ruby -ryaml -e '
    v = YAML.load_file(ARGV[0]); sub = v.fetch("litellm", {}).dup
    sub["global"] = {"environment" => v["global"]["environment"], "namespace" => "platform"}
    File.write(ARGV[1], sub.to_yaml)' \
    "$REPO/argo/environments/$ENV/platform-values.yaml" "$HERE/rendered/subvalues-$ENV.yaml"
  helm template litellm "$CHART" -f "$HERE/rendered/subvalues-$ENV.yaml" \
    --show-only templates/configmap.yaml > "$HERE/rendered/configmap-$ENV.yaml"
  helm template litellm "$CHART" -f "$HERE/rendered/subvalues-$ENV.yaml" \
    --show-only templates/deployment.yaml > "$HERE/rendered/deployment-$ENV.yaml"
  ruby -ryaml -e 'File.write(ARGV[1], YAML.load_file(ARGV[0])["data"]["config.yaml"])' \
    "$HERE/rendered/configmap-$ENV.yaml" "$HERE/rendered/config-$ENV.yaml"
  echo "== $ENV image: $(grep 'image:' "$HERE/rendered/deployment-$ENV.yaml")"
done
