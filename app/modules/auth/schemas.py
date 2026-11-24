from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # Seconds until ``access_token`` expires; renew with POST /auth/refresh
    expires_in: int | None = None
    refresh_token: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10, max_length=2048)


class MessageResponse(BaseModel):
    detail: str


class TokenConfirm(BaseModel):
    token: str = Field(..., min_length=10, max_length=2048)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., min_length=10, max_length=2048)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
