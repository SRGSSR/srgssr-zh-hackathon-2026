# Same image the Public AI Utility runs (charts/platform/charts/litellm/values.yaml).
FROM ghcr.io/forpublicai/litellm-database:v1.92.0
WORKDIR /app
COPY config.yaml policy.py custom_auth.py communes.yaml /app/gateway/
ENV PYTHONPATH=/app/gateway
CMD ["--config", "/app/gateway/config.yaml", "--port", "4000", "--num_workers", "1"]
