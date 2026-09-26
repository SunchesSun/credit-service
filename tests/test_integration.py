import psycopg
import pytest

from credit_service.config import settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not settings.database_url, reason="нужен Postgres: задайте DATABASE_URL"),
]


def test_prediction_is_logged(client, good_row):
    response = client.post("/v1/predict", json=good_row)
    assert response.status_code == 200
    body = response.json()

    with psycopg.connect(settings.database_url) as conn:
        row = conn.execute(
            "SELECT model_version, prediction, features, status_code "
            "FROM predictions WHERE request_id = %s",
            (body["request_id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == body["model_version"]
    assert row[1]["score"] == pytest.approx(body["score"])
    assert row[2] == good_row
    assert row[3] == 200
