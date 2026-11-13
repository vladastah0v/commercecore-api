FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv==0.13.7 \
    && useradd --create-home --uid 10001 appuser

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser migrations/ ./migrations/
COPY --chown=appuser:appuser scripts/ ./scripts/

USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
