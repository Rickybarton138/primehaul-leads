"""
Application error tracking — catches unhandled exceptions, logs to DB,
and provides a structured logging handler.
"""

import logging
import os
import sys
import traceback
from datetime import datetime, timezone

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import SessionLocal
from app.models import ErrorLog


logger = logging.getLogger("primehaul")


def _is_test_mode():
    return "pytest" in sys.modules


def log_error(
    level: str,
    source: str,
    message: str,
    tb: str = None,
    request: Request = None,
    extra: dict = None,
):
    """Write an error record to the database."""
    if _is_test_mode() or SessionLocal is None:
        return  # Skip DB writes in test mode or when DB not configured
    try:
        db = SessionLocal()
        entry = ErrorLog(
            level=level,
            source=source,
            message=message[:2000],
            traceback=tb[:10000] if tb else None,
            request_url=str(request.url)[:500] if request else None,
            request_method=request.method if request else None,
            user_agent=(request.headers.get("user-agent", "")[:500] if request else None),
            ip_address=(request.client.host if request and request.client else None),
            extra=extra,
        )
        db.add(entry)
        db.commit()
    except Exception:
        logger.exception("Failed to write error log to DB")
    finally:
        try:
            db.close()
        except Exception:
            pass


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware that catches unhandled 500 errors and logs them."""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)

            # Log 5xx responses
            if response.status_code >= 500:
                log_error(
                    level="ERROR",
                    source="http_response",
                    message=f"{response.status_code} on {request.method} {request.url.path}",
                    request=request,
                )

            return response
        except Exception as exc:
            tb = traceback.format_exc()
            log_error(
                level="CRITICAL",
                source="unhandled_exception",
                message=str(exc)[:2000],
                tb=tb,
                request=request,
            )
            raise


class DBLogHandler(logging.Handler):
    """Python logging handler that writes ERROR+ records to the error_logs table."""

    def emit(self, record):
        if record.levelno < logging.ERROR:
            return
        try:
            tb = None
            if record.exc_info and record.exc_info[2]:
                tb = "".join(traceback.format_exception(*record.exc_info))

            log_error(
                level=record.levelname,
                source=record.name,
                message=record.getMessage(),
                tb=tb,
                extra={"module": record.module, "funcName": record.funcName, "lineno": record.lineno},
            )
        except Exception:
            pass  # never let logging crash the app
