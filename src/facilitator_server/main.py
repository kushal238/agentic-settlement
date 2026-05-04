"""Facilitator Server entry point."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.eventbus import EventBus
from src.core.facilitator import Facilitator
from src.facilitator_server import config
from src.facilitator_server.node_registry import build_facilitator_config, load_genesis_accounts
from src.facilitator_server.routes import health as health_route
from src.facilitator_server.routes import settle as settle_route
from src.facilitator_server.routes import debug as debug_route
from src.facilitator_server.routes import events as events_route


def create_app(facilitator: Facilitator | None = None) -> FastAPI:
    """Factory so tests can inject a pre-built Facilitator, bypassing startup I/O."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        if facilitator is not None:
            app.state.facilitator = facilitator
            app.state.debug_validators = {}
        else:
            genesis = load_genesis_accounts(config.GENESIS_ACCOUNTS_PATH)
            cfg, debug_registry = build_facilitator_config(
                f=config.BFT_F,
                per_validator_timeout_s=config.PER_VALIDATOR_TIMEOUT_S,
                genesis_accounts=genesis,
            )
            app.state.facilitator = Facilitator(cfg)
            app.state.debug_validators = debug_registry
        # Sync routes (e.g. /settle running in FastAPI's threadpool) cannot
        # call asyncio.get_running_loop() because they aren't on the loop
        # thread. Capture the loop here while we ARE on it; sync code can then
        # use bus.make_threadsafe_publisher(loop) to publish from any thread.
        app.state.event_bus = EventBus()
        app.state.event_loop = asyncio.get_running_loop()
        yield

    _app = FastAPI(title="Facilitator Server", version="1.0.0", lifespan=lifespan)
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _app.include_router(settle_route.router)
    _app.include_router(health_route.router)
    _app.include_router(debug_route.router)
    _app.include_router(events_route.router)
    return _app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.facilitator_server.main:app",
        host="0.0.0.0",
        port=config.FACILITATOR_PORT,
        reload=True,
    )
