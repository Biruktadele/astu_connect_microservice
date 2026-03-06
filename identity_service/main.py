import os
import uvicorn


def serve():
    """Entry point for `uv run serve`. Use RUN_RELOAD=1 for dev reload."""
    reload = os.environ.get("RUN_RELOAD", "false").lower() in ("1", "true", "yes")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=reload)


if __name__ == "__main__":
    serve()
