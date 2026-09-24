FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* "uvicorn[standard]==0.32.*" httpx==0.28.*
WORKDIR /srv
COPY faultbox.py .
EXPOSE 8000
CMD ["uvicorn", "faultbox:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
