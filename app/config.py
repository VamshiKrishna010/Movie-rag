from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    tmdb_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    cerebras_model: str = "gpt-oss-120b"
    jwt_secret_key: str = "change-me-in-production"
    jwt_secret_key_previous: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 30
    jwt_issuer: str = "movie-rag"
    jwt_audience: str = "movie-rag-api"
    login_rate_limit: str = "5/minute"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

settings = Settings()
