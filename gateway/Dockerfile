# Same image the Public AI Utility runs in prod and staging
# (argo/environments/{prod,staging}/platform-values.yaml; the chart default in values.yaml is older).
FROM ghcr.io/forpublicai/litellm-database:v1.98.0
WORKDIR /app
COPY config.yaml policy.py custom_auth.py communes.yaml /app/gateway/
ENV PYTHONPATH=/app/gateway
CMD ["--config", "/app/gateway/config.yaml", "--port", "4000", "--num_workers", "1"]
