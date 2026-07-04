# app/core/logging.py

import logging
import sys
from contextvars import ContextVar

from app.core.config import settings


request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")
connector_id_ctx: ContextVar[str] = ContextVar("connector_id", default="-")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.tenant_id = tenant_id_ctx.get()
        record.user_id = user_id_ctx.get()
        record.connector_id = connector_id_ctx.get()
        return True


def configure_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    log_format = (
        "%(asctime)s | %(levelname)s | "
        "tenant=%(tenant_id)s | "
        "request=%(request_id)s | "
        "user=%(user_id)s | "
        "connector=%(connector_id)s | "
        "%(name)s | %(message)s"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(log_format))
    handler.addFilter(RequestContextFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)

    logging.getLogger("uvicorn.access").setLevel(log_level)
    logging.getLogger("uvicorn.error").setLevel(log_level)