FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml README.md LICENSE ./
COPY graphkit ./graphkit
RUN pip install '.[api,bigquery,spanner,llm,chat]'
# Build with `cd graphkit-web && npm ci && npm run build` first.
# Firebase's public browser configuration is compiled locally; env files are excluded.
COPY graphkit-web/dist ./graphkit-web/dist
RUN python -m graphkit.graph.cli demo
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn graphkit.api.application:app --host 0.0.0.0 --port ${PORT:-8080}"]
