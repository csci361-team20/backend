from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as router_v1
from app.core.config import settings

app = FastAPI(title="BiletFlow API", version="0.1.0")

# TODO: in development change value of ORIGINS in .env to our own values
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router_v1)
