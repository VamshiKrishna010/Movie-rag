import secrets

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, HTTPException, Request, status

from app.auth.google_auth import oauth
from app.config import settings


router = APIRouter(
    prefix="/auth/google",
    tags=["Google Authentication"],
)


@router.get("/login")
async def google_login(request: Request):
    """
    Redirect the browser to Google's sign-in page.
    """

    return await oauth.google.authorize_redirect(
        request=request,
        redirect_uri=settings.google_redirect_uri,
        nonce=secrets.token_urlsafe(32),
    )


@router.get("/callback")
async def google_callback(request: Request):
    """
    Google redirects the browser here after authentication.
    """

    try:
        token = await oauth.google.authorize_access_token(request)

    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Google authentication failed: {exc.error}",
        ) from exc

    userinfo = token.get("userinfo")

    if not userinfo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google did not return user identity information",
        )

    # Temporary test response.
    # We will connect this to your database in the next step.
    return {
        "message": "Google authentication successful",
        "google_user": {
            "sub": userinfo.get("sub"),
            "email": userinfo.get("email"),
            "email_verified": userinfo.get("email_verified"),
            "name": userinfo.get("name"),
            "picture": userinfo.get("picture"),
        },
    }
