from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pandas as pd
import pytest
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INTERNAL_ERROR, RESOURCE_DOES_NOT_EXIST

from credit_service import train


@pytest.mark.parametrize("candidate,champion,expected", [
    (0.6242, None, True),
    (0.6343304540736708, 0.6241999967409972, True),
    (0.6107379541696142, 0.6241999967409972, False),
    (0.6242, 0.6242, False),
    (0.6242 + 0.01, 0.6242, False),
    (0.63, 0.6242, False),
])
def test_gate_decision(candidate, champion, expected):
    assert train.should_promote(candidate, champion, 0.01) is expected


@pytest.mark.parametrize("margin", [-0.01, 1, float("nan"), float("inf")])
def test_invalid_gate_margin_is_rejected(margin):
    with pytest.raises(ValueError, match="GATE_MIN_GAIN"):
        train.should_promote(0.64, None, margin)


@pytest.mark.parametrize("candidate,champion", [
    (float("nan"), 0.62), (0.64, float("inf")), (1.01, None), (0.64, -0.1),
])
def test_invalid_score_is_rejected(candidate, champion):
    with pytest.raises(ValueError, match="PR-AUC"):
        train.should_promote(candidate, champion)


def context():
    return train.evaluation_params("data-md5", pd.Series([0, 1, 0], index=[4, 2, 9]))


def champion_client(params, score=0.6242):
    client = Mock()
    client.get_model_version_by_alias.return_value = SimpleNamespace(version="1", run_id="baseline")
    client.get_run.return_value = SimpleNamespace(data=SimpleNamespace(params=params, metrics={"pr_auc": score}))
    return client


def test_matching_champion_is_comparable():
    expected = context()
    assert train.champion_score(champion_client(expected), expected) == ("1", 0.6242)


@pytest.mark.parametrize("key", ["data_md5", "seed", "test_size", "stratified", "validation_sha256"])
def test_changed_evaluation_is_rejected(key):
    expected = context()
    with pytest.raises(ValueError, match=key):
        train.champion_score(champion_client({**expected, key: "different"}), expected)


def test_legacy_run_without_split_metadata_is_rejected():
    with pytest.raises(ValueError, match="baseline"):
        train.champion_score(champion_client({"data_md5": "data-md5", "seed": "42"}), context())


def test_missing_metric_is_rejected():
    client = champion_client(context())
    client.get_run.return_value.data.metrics = {}
    with pytest.raises(ValueError, match="нет метрики"):
        train.champion_score(client, context())


def test_only_missing_champion_is_treated_as_first_model():
    client = Mock()
    client.get_model_version_by_alias.side_effect = MlflowException("missing", error_code=RESOURCE_DOES_NOT_EXIST)
    assert train.champion_score(client, context()) == (None, None)
    client.get_model_version_by_alias.side_effect = MlflowException("unavailable", error_code=INTERNAL_ERROR)
    with pytest.raises(MlflowException):
        train.champion_score(client, context())


def test_validation_fingerprint_tracks_rows_and_labels():
    baseline = context()["validation_sha256"]
    assert baseline == context()["validation_sha256"]
    assert baseline != train.evaluation_params("data-md5", pd.Series([0, 1, 0], index=[5, 2, 9]))["validation_sha256"]
    assert baseline != train.evaluation_params("data-md5", pd.Series([1, 1, 0], index=[4, 2, 9]))["validation_sha256"]


def test_incomparable_run_stops_before_training_and_alias_changes(monkeypatch, tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("synthetic data")
    monkeypatch.setattr(train, "DATA_PATH", path)
    frame = pd.DataFrame({"feature": range(20)})
    target = pd.Series([0, 1] * 10)
    monkeypatch.setattr(train, "load_and_validate", Mock(return_value=(frame, target, pd.DataFrame())))
    client = champion_client({})
    monkeypatch.setattr(train, "MlflowClient", Mock(return_value=client))
    monkeypatch.setattr(train.mlflow, "set_experiment", Mock())
    monkeypatch.setattr(train.mlflow, "start_run", MagicMock())
    monkeypatch.setattr(train.mlflow, "log_params", Mock())
    fit = Mock()
    monkeypatch.setattr(train, "build_pipeline", fit)
    with pytest.raises(ValueError, match="несопоставимые"):
        train.main()
    fit.assert_not_called()
    client.set_registered_model_alias.assert_not_called()
