from fastapi import FastAPI

from app.api.v1.router import router as router_v1

app = FastAPI(title="BiletFlow API")
app.include_router(router_v1)
