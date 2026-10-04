"""API server (FastAPI). Routes per module live in ``routes/``; request wiring in ``deps.py``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from smart_tutor.apps.api.deps import current_principal
from smart_tutor.apps.api.routes import accounts
from smart_tutor.shared.adapters.auth.keycloak_introspection import keycloak_verifier
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.token_verifier import TokenVerifier

# Everything else needs a token Keycloak says is active (tests/unit/apps/api/test_auth.py checks every route).
PUBLIC_PATHS = frozenset({"/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})


def create_app(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if verifier is not None:
            yield
            return
        async with httpx.AsyncClient(timeout=5) as http:
            app.state.verifier = keycloak_verifier(settings, http)
            yield

    app = FastAPI(title="Smart Tutor API", lifespan=lifespan)
    if verifier is not None:
        app.state.verifier = verifier
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Add protected routes with authentication dependency
    from fastapi.routing import APIRoute

    for route in accounts.router.routes:
        if isinstance(route, APIRoute):
            route.dependencies.append(Depends(current_principal))
            app.routes.append(route)
    return app


app = create_app()
