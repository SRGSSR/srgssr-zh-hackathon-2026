FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY civic ./civic
EXPOSE 8080
CMD ["uvicorn", "civic.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning"]
