from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field

from app.auth.cookies import clear_refresh_cookie, read_refresh_cookie, set_refresh_cookie
from app.auth.deps import get_current_user
from app.auth.scopes import ROLE_SCOPES, scopes_for_role
from app.auth.refresh import RefreshTokenError, issue_token_pair, revoke_refresh_token, rotate_refresh_token
from app.auth.security import hash_password, verify_password
from app.auth.users import create_user, get_user_by_email
from app.config import settings
from app.limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: str
    scopes: list[str]


class RoleScopesOut(BaseModel):
    roles: dict[str, list[str]]


class TokenResponse(BaseModel):
    access_token: str
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
    return UserOut(
        id=user["id"],
        email=user["email"],
        role=user["role"],
        scopes=scopes_for_role(user["role"]),
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.login_rate_limit)
async def login(
    request: Request,
    response: Response,
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
    set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response) -> TokenResponse:
    raw_token = read_refresh_cookie(request)
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        access_token, new_refresh_token = await rotate_refresh_token(raw_token)
    except RefreshTokenError as exc:
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    set_refresh_cookie(response, new_refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> None:
    raw_token = read_refresh_cookie(request)
    if raw_token is not None:
        await revoke_refresh_token(raw_token)
    clear_refresh_cookie(response)


@router.get("/roles", response_model=RoleScopesOut)
async def roles() -> RoleScopesOut:
    return RoleScopesOut(roles={role: list(scopes) for role, scopes in ROLE_SCOPES.items()})


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[dict, Depends(get_current_user)]) -> UserOut:
    return UserOut(
        id=current_user["id"],
        email=current_user["email"],
        role=current_user["role"],
        scopes=current_user["scopes"],
    )

