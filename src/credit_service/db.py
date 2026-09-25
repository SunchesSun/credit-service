import psycopg
from psycopg.types.json import Jsonb

from credit_service.config import settings

DDL = """
CREATE TABLE IF NOT EXISTS predictions (
    request_id uuid PRIMARY KEY,
    ts timestamptz NOT NULL DEFAULT now(),
    model_version text NOT NULL,
    features jsonb NOT NULL,
    prediction jsonb,
    latency_ms double precision NOT NULL,
    status_code integer NOT NULL
)
"""


def init() -> None:
    if settings.database_url:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(7001)")
            conn.execute(DDL)


def save_prediction(request_id, features, prediction, model_version, latency_ms, status_code) -> None:
    if settings.database_url:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            conn.execute(
                "INSERT INTO predictions (request_id, features, prediction, model_version, latency_ms, status_code)" \
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (request_id, Jsonb(features), Jsonb(prediction) if prediction is not None else None, model_version, latency_ms, status_code),
            )
