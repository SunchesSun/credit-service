import pytest

from credit_service.service.app import app


def test_health(client):
    assert client.get("/health").json()["model_version"] == app.state.meta["model_version"]


def test_ready(client):
    assert client.get("/ready").status_code == 200
    pipeline = app.state.pipeline
    app.state.pipeline = None
    try:
        assert client.get("/ready").status_code == 503
    finally:
        app.state.pipeline = pipeline


@pytest.mark.parametrize(
    "changes",
    [
        {"age": -1},
        {"age": 0},
        {"age": 300},
        {"credit_amount": 0},
        {"duration": 0},
        {"duration": "garbage"},
        {"extra": 1},
        {"age": None},
        {"age": True},
        {"job": 4},
        {"sex": "unknown"},
        {"saving_accounts": "unknown"},
        {"purpose": "unknown"},
    ],
)
def test_invalid_features(client, good_row, changes):
    assert client.post("/v1/predict", json={**good_row, **changes}).status_code == 422


def test_missing_field(client, good_row):
    del good_row["credit_amount"]
    assert client.post("/v1/predict", json=good_row).status_code == 422


def test_docs(client):
    assert client.get("/docs").status_code == 200
    assert "/v1/predict" in client.get("/openapi.json").json()["paths"]


def test_optional_accounts(client, good_row):
    row = {k: v for k, v in good_row.items() if k not in {"saving_accounts", "checking_account"}}
    missing = client.post("/v1/predict", json=row)
    explicit = client.post("/v1/predict", json={**row, "saving_accounts": None, "checking_account": None})
    assert missing.status_code == explicit.status_code == 200
    assert missing.json()["score"] == explicit.json()["score"]


def test_values_outside_observed_training_ranges_are_accepted(client, good_row):
    response = client.post(
        "/v1/predict",
        json={**good_row, "age": 76, "credit_amount": 20_000, "duration": 73},
    )
    assert response.status_code == 200


def test_validation_failure_is_audited(client, good_row, monkeypatch):
    from credit_service import db

    records = []
    monkeypatch.setattr(db, "save_prediction", lambda *args: records.append(args))

    response = client.post("/v1/predict", json={**good_row, "age": 0})

    assert response.status_code == 422
    assert len(records) == 1
    assert records[0][2] is None
    assert records[0][-1] == 422


def test_audit_failure_is_fail_closed(client, good_row, monkeypatch):
    from credit_service import db

    def fail(*args):
        raise RuntimeError("test audit failure")

    monkeypatch.setattr(db, "save_prediction", fail)

    response = client.post("/v1/predict", json=good_row)

    assert response.status_code == 503
    assert response.json() == {"detail": "Prediction log unavailable"}
    assert response.headers["X-Request-ID"]
