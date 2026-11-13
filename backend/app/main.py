from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .routers import fhir, patient, staff, webhooks


def create_app() -> FastAPI:
    s = get_settings()
    docs = "/api/docs" if s.show_api_docs else None
    app = FastAPI(title="ReportBox API", version="0.2.0", docs_url=docs, redoc_url=None,
                  openapi_url="/api/openapi.json" if docs else None)

    # The website reaches the API on its own domain (through a proxy), so CORS is only needed when
    # another origin calls the API directly.
    origins = [o.strip() for o in s.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["Authorization", "Content-Type", "X-RB-CSRF"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith(("/api/patient", "/api/staff", "/api/public", "/fhir")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(staff.router)
    app.include_router(patient.router)
    app.include_router(fhir.router)
    app.include_router(webhooks.router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


# Locally, tables are created on start. In production AUTO_CREATE_TABLES=false and
# `alembic upgrade head` runs before the server starts (see the Dockerfile).
if get_settings().auto_create_tables:
    Base.metadata.create_all(engine)
app = create_app()
