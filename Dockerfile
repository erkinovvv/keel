# Web app only; the FISCO BCOS chain runs separately (scripts/fisco_chain.sh) or anchoring falls back gracefully.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
RUN uv sync --frozen --no-dev
ENV HOST=0.0.0.0 PORT=8600 WEALTH_ADVISOR_CATALOG=cn AUDIT_LOG=/app/logs/audit.jsonl LLM_MODE=replay
EXPOSE 8600
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8600/healthz')"
CMD ["uv", "run", "--no-dev", "wealth-advisor-ui"]
