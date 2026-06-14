"""Sympto Web App — FastAPI entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import auth, patient, doctor, admin, internal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting Sympto API (env=%s)", settings.environment)
    yield
    logger.info("Shutting down Sympto API")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Sympto API",
        description="Healthcare platform — connects patients with doctors.",
        version="1.0.0",
        docs_url="/docs" if settings.environment == "dev" else None,
        redoc_url="/redoc" if settings.environment == "dev" else None,
        lifespan=lifespan,
    )

    # CORS — allow configured frontend URL + localhost dev origins
    origins = [
        settings.frontend_url,
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(auth.router)
    app.include_router(patient.router)
    app.include_router(doctor.router)
    app.include_router(admin.router)
    app.include_router(internal.router)

    # Serve test UI
    import os
    templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    if os.path.isdir(templates_dir):
        app.mount("/ui", StaticFiles(directory=templates_dir, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    async def root():
        index = os.path.join(templates_dir, "index.html") if os.path.isdir(templates_dir) else None
        if index and os.path.isfile(index):
            return FileResponse(index)
        return {"service": "Sympto API", "version": "1.0.0", "status": "running"}

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)
