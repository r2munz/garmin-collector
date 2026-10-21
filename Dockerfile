FROM python:3.11-slim-bookworm

ENV PDM_CHECK_UPDATE=false \
    PDM_VENV_IN_PROJECT=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN pip install --no-cache-dir pdm

COPY pyproject.toml pdm.lock README.md ./
COPY src ./src

RUN pdm install --prod --frozen-lockfile --no-editable

ENV PATH="/app/.venv/bin:${PATH}"

RUN mkdir -p /data /tokens

CMD ["python", "-m", "garmin_collector.main"]
