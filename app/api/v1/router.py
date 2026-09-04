from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

@router.get("/")
def root():
    return {"system": "on"}
