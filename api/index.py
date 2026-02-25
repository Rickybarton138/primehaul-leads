"""Vercel serverless entry point — re-exports the FastAPI ASGI app."""

import traceback

try:
    from app.main import app
except Exception:
    # Surface the import error as an HTTP response so we can debug
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI()

    _tb = traceback.format_exc()

    @app.get("/{path:path}")
    async def catch_all(path: str):
        return PlainTextResponse(_tb, status_code=500)
