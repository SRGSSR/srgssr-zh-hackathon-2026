#!/bin/sh
# Run test_utility_config.py inside the image the Utility runs in prod/staging.
HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${IMAGE:-ghcr.io/forpublicai/litellm-database:v1.98.0}"
exec docker run --rm -v "$HERE":/t -w /t -e PYTHONPATH=/t -e LITELLM_LOG=ERROR --entrypoint python "$IMAGE" test_utility_config.py
