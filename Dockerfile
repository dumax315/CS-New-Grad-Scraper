FROM node:22-slim AS codex

RUN npm install --global @openai/codex@0.145.0

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=codex /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-*/vendor/*/ /opt/codex/
RUN ln -s /opt/codex/bin/codex /usr/local/bin/codex

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY README.md ./
RUN pip install --upgrade pip && pip install .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
