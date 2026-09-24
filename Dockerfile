FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
COPY src ./src
COPY data ./data
RUN uv sync --no-dev
ENV SGM_TRANSPORT=streamable-http SGM_HOST=0.0.0.0 PORT=8000 SGM_CACHE_DIR=/tmp/sgm-cache
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "swiss-grounding-mcp"]
