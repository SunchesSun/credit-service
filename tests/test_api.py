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
        {"age": 76},
        {"credit_amount": 0},
        {"credit_amount": 18425},
        {"duration": 73},
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
