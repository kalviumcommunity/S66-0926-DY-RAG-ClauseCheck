import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from clausecheck.api.container import AppContainer
from clausecheck.api.routes import (
    catalog,
    chat,
    contracts,
    documents,
    feedback,
    health,
    insights,
    sessions,
)
from clausecheck.core.config import get_settings
from clausecheck.core.logging import RedactionFilter, setup_logging


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


def create_app(container: AppContainer | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if container is None:
            settings = get_settings()
            setup_logging(settings)
            c = AppContainer.from_settings(settings)
            app.state.container = c
            # redaction filter
            secrets = []
            for name, field in settings.__class__.model_fields.items():
                if "SecretStr" in str(field.annotation):
                    val = getattr(settings, name)
                    if val is not None:
                        secrets.append(val.get_secret_value())
            filt = RedactionFilter(secrets)
            logging.getLogger("clausecheck.api").addFilter(filt)
            yield
            try:
                c.conn.close()
            except Exception:
                pass
        else:
            app.state.container = container
            yield

    app = FastAPI(lifespan=lifespan)
    if container is not None:
        app.state.container = container

    # CORS
    settings = container.settings if container is not None else get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        logging.getLogger("clausecheck.api").error(
            "unhandled error request_id=%s type=%s", rid, type(exc).__name__
        )
        return JSONResponse(
            status_code=500, content={"detail": "internal error", "request_id": rid}
        )

    app.include_router(sessions.router)
    app.include_router(chat.router)
    app.include_router(catalog.router)
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(feedback.router)
    app.include_router(insights.router)
    app.include_router(contracts.router)

    if container is not None:
        app.state.container = container
    return app


def get_app() -> FastAPI:
    return create_app()
