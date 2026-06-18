from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field

from app.auth.deps import get_current_user, require_admin
from app.auth.refresh import RefreshTokenError, issue_token_pair, revoke_refresh_token, rotate_refresh_token
from app.auth.security import hash_password, verify_password
from app.auth.users import create_user, get_user_by_email
from app.config import settings
from app.limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.login_rate_limit)
async def register(request: Request, req: RegisterRequest) -> UserOut:
    existing = await get_user_by_email(req.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await create_user(req.email, hash_password(req.password))
    return UserOut(id=user["id"], email=user["email"], role=user["role"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.login_rate_limit)
async def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    user = await get_user_by_email(form.username)
    if user is None or not verify_password(form.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, refresh_token = await issue_token_pair(user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest) -> TokenResponse:
    try:
        access_token, refresh_token = await rotate_refresh_token(req.refresh_token)
    except RefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(req: LogoutRequest) -> None:
    await revoke_refresh_token(req.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[dict, Depends(get_current_user)]) -> UserOut:
    return UserOut(
        id=current_user["id"],
        email=current_user["email"],
        role=current_user["role"],
    )


@router.get("/admin/ping")
async def admin_ping(_admin: Annotated[dict, Depends(require_admin)]) -> dict:
    return {"status": "ok"}
