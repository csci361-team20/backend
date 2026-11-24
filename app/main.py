from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as router_v1
from app.core.config import settings
from app.core.storage import MEDIA_ROUTE

app = FastAPI(title="BiletFlow API", version="0.1.0")

# Only the sites in ORIGINS (the website by default) may call the API from a browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router_v1)

if settings.STORAGE_BACKEND == "local":
    # Uploaded images; under /api/v1 so the frontend's proxy reaches them
    Path(settings.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
    app.mount(MEDIA_ROUTE, StaticFiles(directory=settings.MEDIA_DIR), name="media")
