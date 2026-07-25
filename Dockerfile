FROM node:22-slim AS codex

RUN npm install --global @openai/codex@0.145.0

FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=codex /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-*/vendor/*/ /opt/codex/
RUN ln -s /opt/codex/bin/codex /usr/local/bin/codex
COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY README.md ./
RUN uv sync --locked --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
