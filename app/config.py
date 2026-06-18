from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    tmdb_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    cerebras_model: str = "gpt-oss-120b"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
