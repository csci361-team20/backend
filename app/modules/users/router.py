from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/users")


@router.get("/")
async def get_all_users():
    return {"1": "neo"}
