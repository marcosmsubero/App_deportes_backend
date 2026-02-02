from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DEV: bool = False
    SECRET_KEY: str = "change_me_in_env"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

settings = Settings()


