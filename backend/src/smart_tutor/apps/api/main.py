"""API server (FastAPI). Routes per module live in ``routes/``; request wiring in ``deps.py``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter

from smart_tutor.apps.api.deps import current_principal
from smart_tutor.apps.api.routes import accounts, insights, knowledge, subjects, threads
from smart_tutor.apps.api.services import ApiServices, build_services
from smart_tutor.shared.adapters.auth.keycloak_introspection import keycloak_verifier
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.token_verifier import TokenVerifier

# Everything else needs a token Keycloak says is active (tests/unit/apps/api/test_auth.py checks every route).
PUBLIC_PATHS = frozenset({"/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})


def include_protected(app: FastAPI, router: APIRouter) -> None:
    """Include a router on the app with authentication required on all its routes."""
    app.include_router(router, dependencies=[Depends(current_principal)])


def create_app(
    settings: Settings | None = None, verifier: TokenVerifier | None = None, services: ApiServices | None = None
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if verifier is not None:
            yield
            return
        if not settings.keycloak_client_secret.get_secret_value():
            raise RuntimeError("SMART_TUTOR_KEYCLOAK_CLIENT_SECRET is not set")
        if services is None:
            app.state.services = build_services(settings)
        async with httpx.AsyncClient(timeout=5) as http:
            app.state.verifier = keycloak_verifier(settings, http)
            yield

    app = FastAPI(title="Smart Tutor API", lifespan=lifespan, root_path=settings.root_path)
    if verifier is not None:
        app.state.verifier = verifier
    if services is not None:
        app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    include_protected(app, accounts.router)
    include_protected(app, insights.router)
    include_protected(app, knowledge.router)
    include_protected(app, subjects.router)
    include_protected(app, threads.router)
    return app


app = create_app()
