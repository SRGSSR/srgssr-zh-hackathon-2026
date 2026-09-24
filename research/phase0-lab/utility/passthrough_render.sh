#!/bin/sh
# Experiment: does templates/configmap.yaml pass arbitrary model_info / litellm_params keys through?
# 1) copies the chart into the lab (clone untouched)
# 2) adds the PROPOSED jurisdiction schema to models/swiss-ai/apertus-v1.5-70b.yaml (see apertus-v1.5-70b.proposed.yaml)
# 3) renders prod with the CURRENT template   -> rendered/passthrough-current-prod.yaml
# 4) applies configmap-modelinfo-passthrough.patch and renders again -> rendered/passthrough-patched-prod.yaml
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
export DOCKER_CONFIG="$HERE/.helmtmp"; mkdir -p "$DOCKER_CONFIG"
export HELM_REGISTRY_CONFIG="$DOCKER_CONFIG/reg.json" HELM_CACHE_HOME="$DOCKER_CONFIG/c" HELM_CONFIG_HOME="$DOCKER_CONFIG/cfg" HELM_DATA_HOME="$DOCKER_CONFIG/d"
SRC="$HERE/../../chat.publicai.co/charts/platform/charts/litellm"
DST="$HERE/chart-copy"
rm -rf "$DST"; cp -R "$SRC" "$DST"
cp "$HERE/apertus-v1.5-70b.proposed.yaml" "$DST/models/swiss-ai/apertus-v1.5-70b.yaml"

show() {
  ruby -ryaml -e 'c = YAML.load(YAML.load_file(ARGV[0])["data"]["config.yaml"])
    c["model_list"].select{|m| m["model_name"]=="swiss-ai/apertus-v1.5-70b"}.each{|m| puts m.to_yaml}' "$1"
  for k in jurisdiction datacenter_country hosting_provider "tags:" "id:"; do
    printf "  %-20s occurrences: " "$k"; grep -c -- "$k" "$1" || true; done
}
helm template litellm "$DST" -f "$HERE/rendered/subvalues-prod.yaml" --show-only templates/configmap.yaml > "$HERE/rendered/passthrough-current-prod.yaml"
echo "=== CURRENT template, apertus-v1.5-70b as rendered:"; show "$HERE/rendered/passthrough-current-prod.yaml"

patch -s -p5 -d "$DST" < "$HERE/configmap-modelinfo-passthrough.patch"
helm template litellm "$DST" -f "$HERE/rendered/subvalues-prod.yaml" --show-only templates/configmap.yaml > "$HERE/rendered/passthrough-patched-prod.yaml"
echo "=== PATCHED template, apertus-v1.5-70b as rendered:"; show "$HERE/rendered/passthrough-patched-prod.yaml"
ruby -ryaml -e 'File.write(ARGV[1], YAML.load_file(ARGV[0])["data"]["config.yaml"])' \
  "$HERE/rendered/passthrough-patched-prod.yaml" "$HERE/rendered/config-prod-patched.yaml"
echo "=== patched render: other models unchanged apart from model_info formatting?"
diff "$HERE/rendered/config-prod.yaml" "$HERE/rendered/config-prod-patched.yaml" | grep '^[<>]' | grep -v -E 'jurisdiction|datacenter|hosting|tags|jurisdiction:CH|id: |evidence|verified|subprocessors|- jurisdiction' | head -20 || true
