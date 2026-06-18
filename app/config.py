from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    tmdb_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    cerebras_model: str = "gpt-oss-120b"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
