from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_path: str = "artifact/model.joblib"
    database_url: str | None = None
    model_config = {"env_file": ".env"}


settings = Settings()
