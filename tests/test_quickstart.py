import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mlflow.exceptions import MlflowException


@pytest.fixture()
def prepare():
    path = Path(__file__).resolve().parents[1] / "scripts/prepare.py"
    spec = importlib.util.spec_from_file_location("quickstart_prepare", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_preserves_original_ids_and_na(prepare, monkeypatch):
    source = b",Age,Saving accounts,Checking account\n0,35,NA,little\n1,40,NA,NA\n2,50,rich,NA\n"
    expected = b",Age,Saving accounts,Checking account\n0,35,NA,little\n2,50,rich,NA\n"
    monkeypatch.setattr(prepare, "SOURCE_MD5", hashlib.md5(source).hexdigest())
    assert prepare.reproduce_csv(source, hashlib.md5(expected).hexdigest()) == expected
    with pytest.raises(ValueError, match="DVC-указателю"):
        prepare.reproduce_csv(source, "0" * 32)


def test_changed_upstream_is_rejected(prepare):
    with pytest.raises(ValueError, match="источника Kaggle"):
        prepare.reproduce_csv(b"unexpected upstream content", "0" * 32)


def test_local_edits_are_not_overwritten(prepare, tmp_path):
    path = tmp_path / "data.csv"
    path.write_bytes(b"local edits")
    with pytest.raises(ValueError, match="локальные изменения"):
        prepare.check_existing(path, "0" * 32)
    assert path.read_bytes() == b"local edits"


@pytest.mark.parametrize("lookup", [
    SimpleNamespace(version="7"),
    MlflowException("Tracking server unavailable", error_code="INTERNAL_ERROR"),
])
def test_existing_champion_or_tracking_failure_does_not_train(prepare, monkeypatch, lookup):
    monkeypatch.setattr(prepare.mlflow, "set_tracking_uri", Mock())
    monkeypatch.setattr(prepare.mlflow, "set_experiment", Mock())
    monkeypatch.setattr(prepare, "validate_file", Mock())
    client = Mock()
    if isinstance(lookup, Exception):
        client.get_model_version_by_alias.side_effect = lookup
    else:
        client.get_model_version_by_alias.return_value = lookup
    monkeypatch.setattr(prepare, "MlflowClient", Mock(return_value=client))
    train = Mock()
    monkeypatch.setattr("credit_service.train.main", train)
    if isinstance(lookup, Exception):
        with pytest.raises(MlflowException):
            prepare.prepare_model()
    else:
        prepare.prepare_model()
    train.assert_not_called()
