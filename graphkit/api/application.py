"""Configurable web entrypoint: GRAPHKIT_ENABLED=false runs chat without GraphKit."""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from graphkit.shared.config import chat_enabled
from graphkit.shared.config import graphkit_enabled


def create_app() -> FastAPI:
    enabled = graphkit_enabled()
    if enabled:
        from graphkit.graph.api import app
        return app

    if not chat_enabled():
        raise ValueError("Enable GRAPHKIT_ENABLED or CHAT_ENABLED; both are disabled.")

    # No graph workflows, adapters, semantic embeddings or graph benchmarks imported.
    from graphkit.chat.api import router
    from graphkit.shared.models import DEFAULTS
    from graphkit.shared.models import GENERATION_MODELS

    app = FastAPI(title="Chat assistant")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/api/capabilities")
    def capabilities():
        return {"graphkit": False, "chat": True}

    @app.get("/api/models")
    def models():
        return {"embedding_models": [], "generation_models": GENERATION_MODELS,
                "defaults": {**DEFAULTS, "embedding_model": "",
                             "generation_model": os.getenv("CHAT_MODEL", DEFAULTS["generation_model"])},
                "note": "Standalone chat does not require embeddings or an approved graph."}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    frontend = Path(os.getenv("GRAPHKIT_FRONTEND", "graphkit-web/dist"))
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
