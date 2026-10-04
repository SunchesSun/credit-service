from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_path: str = "artifact/model.joblib"
    model_name: str | None = None
    model_alias: str = "champion"
    mlflow_tracking_uri: str | None = None
    database_url: str | None = None
    log_level: str = "WARNING"
    model_config = {"env_file": ".env"}


settings = Settings()
