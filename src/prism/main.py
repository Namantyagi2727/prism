from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import make_asgi_app

from prism.api.admin import router as admin_router
from prism.api.chat import router as chat_router
from prism.api.health import router as health_router
from prism.config import settings
from prism.db.session import engine
from prism.observability.tracing import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_tracing(settings.otel_endpoint)
    yield
    await engine.dispose()


app = FastAPI(title="Prism LLM Gateway", version="0.4.0", lifespan=lifespan)

FastAPIInstrumentor.instrument_app(app)
app.mount("/metrics", make_asgi_app())

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(chat_router)
