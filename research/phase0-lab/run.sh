#!/bin/sh
# Run a python script from this lab dir inside the exact LiteLLM image the Utility uses (v1.92.0).
# Usage: ./run.sh script.py [args...]      (for the proxy: ./run.sh -m litellm ... or use docker directly)
LAB="$(cd "$(dirname "$0")" && pwd)"
exec docker run --rm -v "$LAB":/lab -w /lab -e PYTHONPATH=/lab -e LITELLM_LOG=${LITELLM_LOG:-ERROR} --entrypoint python ${IMAGE:-ghcr.io/forpublicai/litellm-database:v1.92.0} "$@"
