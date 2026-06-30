from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    tmdb_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    jwt_secret_key: str = ""
    jwt_secret_key_previous: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 30
    jwt_issuer: str = "movie-rag"
    jwt_audience: str = "movie-rag-api"
    login_rate_limit: str = "5/minute"
    refresh_cookie_name: str = "mr_refresh"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: str = "lax"
    cors_origins: str = "http://localhost:5173"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    oauth_session_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

_INSECURE_SECRETS = {"", "change-me-in-production", "secret", "changeme"}
if settings.jwt_secret_key in _INSECURE_SECRETS or len(settings.jwt_secret_key) < 32:
    raise RuntimeError(
        "JWT_SECRET_KEY must be set to a strong value (>=32 chars). "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
