# Stage 1: Build
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for faster builds
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project files
COPY pyproject.toml .
# COPY uv.lock . # Uncomment if you have a lock file

# Create virtual environment and install dependencies
RUN uv venv /app/.venv && \
    uv pip install .

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Copy the application code
COPY . .

# "Activate" the virtual environment by adding it to PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Now 'python' automatically points to the venv's python
CMD ["python", "main.py"]

