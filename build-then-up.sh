#!/usr/bin/env bash
# Build images one at a time to avoid resource contention and "stuck" builds, then start.
set -e
export COMPOSE_PARALLEL_LIMIT=1
echo "Building images one at a time (this may take several minutes on first run)..."
docker compose build
echo "Starting services..."
docker compose up "$@"
