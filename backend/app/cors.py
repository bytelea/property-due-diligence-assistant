"""Explicit browser-origin allowlist, configured once at application startup."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import Settings


def configure_cors(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )
