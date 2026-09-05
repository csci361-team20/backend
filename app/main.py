from fastapi import FastAPI

from app.modules.users.router import router as users_router

app = FastAPI(title="BiletFlow API")
app.include_router(users_router)
