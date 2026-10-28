from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.api.chat import router as chat_router
from app.api.errors import ChatAPIError
from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import create_database_engine, create_session_factory
from app.providers.base import AIProvider
from app.providers.registry import create_provider

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    provider: AIProvider | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    database_engine = engine or create_database_engine(app_settings.database_url)
    ai_provider = provider or create_provider(app_settings)
    configure_logging(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            with database_engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
        except SQLAlchemyError:
            database_engine.dispose()
            logger.exception("Application startup failed: database unavailable")
            raise
        yield
        database_engine.dispose()

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.engine = database_engine
    application.state.session_factory = create_session_factory(database_engine)
    application.state.ai_provider = ai_provider

    @application.exception_handler(ChatAPIError)
    async def chat_api_error_handler(_, exc: ChatAPIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": [
                        {
                            "location": [str(part) for part in item["loc"]],
                            "message": item["msg"],
                            "type": item["type"],
                        }
                        for item in exc.errors()
                    ],
                }
            },
        )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
    )
    application.include_router(router)
    application.include_router(chat_router)
    return application


app = create_app()
