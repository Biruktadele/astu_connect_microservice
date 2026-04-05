FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY pyproject.toml .
ENV UV_HTTP_TIMEOUT=120 UV_HTTP_RETRIES=6
RUN uv venv /app/.venv && (uv pip install . || uv pip install . || uv pip install .)
RUN /app/.venv/bin/python -c "from nudenet import NudeDetector; NudeDetector()" || true

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /root/.NudeNet /root/.NudeNet
COPY . .
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
