from types import SimpleNamespace

import mlflow
import mlflow.sklearn

from credit_service import model_store
from credit_service.config import settings


def test_load_model_from_registry(monkeypatch):
    monkeypatch.setattr(settings, "model_name", "german-credit")
    monkeypatch.setattr(settings, "model_alias", "champion")
    monkeypatch.setattr(settings, "mlflow_tracking_uri", "http://mlflow.localhost")

    calls = {}
    pipeline = object()
    metadata = {"features": ["age"], "threshold": 0.5}

    def get_model_version_by_alias(name, alias):
        calls["alias"] = (name, alias)
        return SimpleNamespace(version="2", run_id="run-id")

    def load_pipeline(uri):
        calls["model_uri"] = uri
        return pipeline

    def load_metadata(uri):
        calls["metadata_uri"] = uri
        return metadata.copy()

    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: calls.update(tracking_uri=uri))
    monkeypatch.setattr(mlflow, "MlflowClient", lambda: SimpleNamespace(get_model_version_by_alias=get_model_version_by_alias))
    monkeypatch.setattr(mlflow.sklearn, "load_model", load_pipeline)
    monkeypatch.setattr(mlflow.artifacts, "load_dict", load_metadata)

    loaded_pipeline, loaded_metadata, version = model_store.load_model()

    assert loaded_pipeline is pipeline
    assert version == loaded_metadata["model_version"] == "german-credit-v2"
    assert calls == {
        "tracking_uri": "http://mlflow.localhost",
        "alias": ("german-credit", "champion"),
        "model_uri": "models:/german-credit/2",
        "metadata_uri": "runs:/run-id/metadata.json",
    }
