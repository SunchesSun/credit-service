"""Метрики сервиса"""

from prometheus_client import Counter, Histogram, Info


HTTP_LATENCY_BUCKETS = (0.01, 0.025, 0.04, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1, 2)

MODEL_INFO = Info("credit_model", "Loaded credit scoring model")
# Score — вероятность bad в [0, 1] по контракту Prediction.
MODEL_SCORE = Histogram(
    "credit_model_score", "Score of predictions returned with HTTP 200",
    ["model_version"], buckets=(0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1),
)
MODEL_PREDICTIONS = Counter(
    "credit_model_predictions_total", "Predictions returned with HTTP 200",
    ["model_version", "risk"],
)


def initialize(version: str) -> None:
    MODEL_INFO.info({"model_version": version})
    MODEL_SCORE.labels(model_version=version)
    for risk in ("good", "bad"):
        MODEL_PREDICTIONS.labels(model_version=version, risk=risk)


def observe_prediction(version: str, prediction: dict) -> None:
    MODEL_SCORE.labels(model_version=version).observe(prediction["score"])
    MODEL_PREDICTIONS.labels(
        model_version=version, risk="bad" if prediction["is_bad_risk"] else "good",
    ).inc()
