from uuid import UUID


def test_predict_smoke(client, good_row):
    response = client.post("/v1/predict", json=good_row)
    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["score"] <= 1
    assert isinstance(body["is_bad_risk"], bool)
    assert body["latency_ms"] >= 0
    assert body["model_version"]
    assert str(UUID(body["request_id"])) == response.headers["X-Request-ID"]


def test_determinism(client, good_row):
    first = client.post("/v1/predict", json=good_row).json()
    second = client.post("/v1/predict", json=good_row).json()
    assert first["score"] == second["score"]
    assert first["is_bad_risk"] == second["is_bad_risk"]
    assert first["request_id"] != second["request_id"]


def test_failed_inference_is_audited(client, good_row, monkeypatch):
    from credit_service import db
    from credit_service.service.app import app

    records = []
    monkeypatch.setattr(db, "save_prediction", lambda *args: records.append(args))

    def fail(frame):
        raise RuntimeError("test failure")

    monkeypatch.setattr(app.state.pipeline, "predict_proba", fail)
    assert client.post("/v1/predict", json=good_row).status_code == 500
    assert len(records) == 1
    assert records[0][-1] == 500
    assert records[0][2] is None
