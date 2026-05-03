"""API Server entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api_server import config
from src.api_server.routes import health as health_route
from src.api_server.routes import resource as resource_route


def create_app(http_client: httpx.AsyncClient | None = None) -> FastAPI:
    """Factory so tests can inject a mock AsyncClient instead of a real one."""
    owns_client = http_client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.http_client = http_client if http_client is not None else httpx.AsyncClient()
        try:
            yield
        finally:
            if owns_client:
                await app.state.http_client.aclose()

    _app = FastAPI(title="API Server", version="1.0.0", lifespan=lifespan)
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _app.include_router(resource_route.router)
    _app.include_router(health_route.router)
    return _app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api_server.main:app",
        host="0.0.0.0",
        port=config.API_PORT,
        reload=True,
    )
