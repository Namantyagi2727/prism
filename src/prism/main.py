from fastapi import FastAPI

from prism.api.health import router as health_router

app = FastAPI(title="Prism LLM Gateway", version="0.1.0")

app.include_router(health_router)
