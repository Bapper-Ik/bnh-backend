# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH" PORT=10000
WORKDIR /app
RUN groupadd --gid 10001 custodian && useradd --uid 10001 --gid custodian --create-home custodian
COPY --from=builder --chown=custodian:custodian /app/.venv /app/.venv
COPY --chown=custodian:custodian app ./app
COPY --chown=custodian:custodian migrations ./migrations
COPY --chown=custodian:custodian scripts ./scripts
COPY --chown=custodian:custodian alembic.ini ./
RUN chmod +x /app/scripts/start.sh
USER custodian
EXPOSE 10000
CMD ["/app/scripts/start.sh"]
