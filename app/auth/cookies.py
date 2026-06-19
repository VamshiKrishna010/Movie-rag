from fastapi import Request, Response

from app.config import settings

REFRESH_COOKIE_PATH = "/auth"


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    max_age = settings.jwt_refresh_expire_days * 86400
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=REFRESH_COOKIE_PATH,
        max_age=max_age,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=REFRESH_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )


def read_refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(settings.refresh_cookie_name)
