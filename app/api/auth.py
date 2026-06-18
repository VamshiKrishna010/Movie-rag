from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field

from app.auth.deps import get_current_user
from app.auth.security import create_access_token, hash_password, verify_password
from app.auth.users import create_user, get_user_by_email

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest) -> UserOut:
    existing = await get_user_by_email(req.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await create_user(req.email, hash_password(req.password))
    return UserOut(id=user["id"], email=user["email"])


@router.post("/login", response_model=TokenResponse)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenResponse:
    user = await get_user_by_email(form.username)
    if user is None or not verify_password(form.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=user["email"])
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[dict, Depends(get_current_user)]) -> UserOut:
    return UserOut(id=current_user["id"], email=current_user["email"])
