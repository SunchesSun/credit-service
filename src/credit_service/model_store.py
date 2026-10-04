import joblib

from credit_service.config import settings


def load_model() -> tuple[object, dict, str]:
    """Загрузить локальный артефакт или версию модели по алиасу из MLflow."""
    if not settings.model_name:
        bundle = joblib.load(settings.model_path)
        return bundle["pipeline"], bundle["metadata"], bundle["metadata"]["model_version"]

    import mlflow
    import mlflow.sklearn
    from mlflow import MlflowClient

    if settings.mlflow_tracking_uri:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mv = MlflowClient().get_model_version_by_alias(settings.model_name, settings.model_alias)
    pipeline = mlflow.sklearn.load_model(f"models:/{settings.model_name}/{mv.version}")
    meta = mlflow.artifacts.load_dict(f"runs:/{mv.run_id}/metadata.json")
    version = f"{settings.model_name}-v{mv.version}"
    meta["model_version"] = version
    return pipeline, meta, version
