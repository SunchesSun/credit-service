from prometheus_client.parser import text_string_to_metric_families

from credit_service import db
from credit_service.service.app import app


def samples(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    return [sample for family in text_string_to_metric_families(response.text) for sample in family.samples]


def value(client, name, labels):
    return next((sample.value for sample in samples(client) if sample.name == name and sample.labels == labels), 0)


def test_model_version_is_exposed_without_predictions(client):
    assert value(client, "credit_model_info", {"model_version": app.state.version}) == 1


def test_successful_prediction_updates_score_and_risk(client, good_row):
    version = {"model_version": app.state.version}
    before = value(client, "credit_model_score_count", version)
    good_before = value(client, "credit_model_predictions_total", {**version, "risk": "good"})
    bad_before = value(client, "credit_model_predictions_total", {**version, "risk": "bad"})

    response = client.post("/v1/predict", json=good_row)
    assert response.status_code == 200
    body = response.json()

    assert value(client, "credit_model_score_count", version) == before + 1
    assert value(client, "credit_model_predictions_total", {**version, "risk": "good"}) == good_before + (not body["is_bad_risk"])
    assert value(client, "credit_model_predictions_total", {**version, "risk": "bad"}) == bad_before + body["is_bad_risk"]
    http_labels = {"handler": "/v1/predict", "method": "POST", "status": "200"}
    assert value(client, "http_requests_total", http_labels) >= 1
    assert all("request_id" not in sample.labels for sample in samples(client))


def test_rejected_request_does_not_update_score(client, good_row):
    labels = {"model_version": app.state.version}
    before = value(client, "credit_model_score_count", labels)
    assert client.post("/v1/predict", json={**good_row, "age": 0}).status_code == 422
    assert value(client, "credit_model_score_count", labels) == before


def test_audit_failure_does_not_update_score(client, good_row, monkeypatch):
    def fail(*args):
        raise RuntimeError("test audit failure")

    monkeypatch.setattr(db, "save_prediction", fail)
    labels = {"model_version": app.state.version}
    before = value(client, "credit_model_score_count", labels)
    assert client.post("/v1/predict", json=good_row).status_code == 503
    assert value(client, "credit_model_score_count", labels) == before
