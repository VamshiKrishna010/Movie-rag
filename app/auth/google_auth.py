from authlib.integrations.starlette_client import OAuth

from app.config import settings


oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,

    # Google OpenID Connect discovery document
    server_metadata_url=(
        "https://accounts.google.com/.well-known/openid-configuration"
    ),

    client_kwargs={
        "scope": "openid email profile",
        "code_challenge_method": "S256",
    },
)