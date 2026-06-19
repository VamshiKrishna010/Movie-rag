from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.auth.scopes import Scope, scopes_for_role
from app.auth.security import decode_access_token
from app.auth.users import get_user_by_email

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/auth/login",
    auto_error=False,
)


def _user_payload(user: dict) -> dict:
    role = user["role"]
    scopes = scopes_for_role(role)
    return {
        "id": user["id"],
        "email": user["email"],
        "role": role,
        "scopes": scopes,
    }


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> dict:
    email = decode_access_token(token)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_email(email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _user_payload(user)


async def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
) -> dict | None:
    if token is None:
        return None

    email = decode_access_token(token)
    if email is None:
        return None

    user = await get_user_by_email(email)
    if user is None:
        return None

    return _user_payload(user)


def require_scopes(*required: Scope):
    async def dependency(
        current_user: Annotated[dict, Depends(get_current_user)],
    ) -> dict:
        missing = [scope for scope in required if scope not in current_user["scopes"]]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing scopes: {', '.join(missing)}",
            )
        return current_user

    return dependency


async def require_admin(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
