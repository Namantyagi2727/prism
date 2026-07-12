from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from prism.api.admin import router as admin_router
from prism.api.chat import router as chat_router
from prism.api.health import router as health_router
from prism.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


app = FastAPI(title="Prism LLM Gateway", version="0.2.0", lifespan=lifespan)

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(chat_router)
