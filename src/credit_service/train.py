"""Обучение кредитного скоринга из notebooks/train.ipynb и регистрация в MLflow.

MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m credit_service.train
"""

import hashlib
import json
import os
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd
import sklearn
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, average_precision_score, confusion_matrix, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA_PATH = Path(os.getenv("DATA_PATH", "datasets/german_credit_data.csv"))
MODEL_NAME = os.getenv("MODEL_NAME", "german-credit")
EXPERIMENT = os.getenv("MLFLOW_EXPERIMENT", "german-credit")
C = float(os.getenv("C", "1.0"))
# В исходном CSV bad встречается реже good (см. class_counts в metadata.json).
# PR-AUC оценивает ранжирование bad; 0.01 — выбранный минимальный прирост
# для смены champion при почти одинаковом результате.
MIN_GAIN = float(os.getenv("GATE_MIN_GAIN", "0.01"))
SEED = 42
THRESHOLD = 0.5
SKOPS_TRUSTED = ["numpy.dtype", "sklearn.compose._column_transformer._RemainderColsList"]

# Соответствие заголовка CSV и контракта сервиса взято из notebooks/train.ipynb.
COLUMNS = {
    "Age": "age",
    "Sex": "sex",
    "Job": "job",
    "Housing": "housing",
    "Saving accounts": "saving_accounts",
    "Checking account": "checking_account",
    "Credit amount": "credit_amount",
    "Duration": "duration",
    "Purpose": "purpose",
}
FEATURES = list(COLUMNS.values())
NUMERIC = ["age", "credit_amount", "duration"]
CATEGORICAL = [name for name in FEATURES if name not in NUMERIC]


def load_and_validate(path: Path) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    data = pd.read_csv(path)
    missing = (set(COLUMNS) | {"Risk"}) - set(data.columns)
    if missing:
        raise ValueError(f"В данных нет колонок: {sorted(missing)}")
    if set(data["Risk"].unique()) != {"good", "bad"}:
        raise ValueError("Ожидались оба значения Risk: good и bad")
    frame = data[list(COLUMNS)].rename(columns=COLUMNS)
    target = data["Risk"].eq("bad").astype(int)
    return frame, target, data


def build_pipeline(c: float) -> Pipeline:
    categorical = Pipeline([
        ("impute", SimpleImputer(strategy="constant", fill_value="missing")),
        ("encode", OneHotEncoder(handle_unknown="ignore")),
    ])
    preprocess = ColumnTransformer([
        ("numeric", StandardScaler(), NUMERIC),
        ("categorical", categorical, CATEGORICAL),
    ])
    return Pipeline([
        ("preprocess", preprocess),
        ("model", LogisticRegression(max_iter=1000, random_state=SEED, C=c)),
    ])


def champion_score(client: MlflowClient) -> tuple[str | None, float | None]:
    try:
        version = client.get_model_version_by_alias(MODEL_NAME, "champion")
    except MlflowException as exc:
        if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
            raise
        return None, None
    score = client.get_run(version.run_id).data.metrics.get("pr_auc")
    if score is None:
        raise ValueError(f"У champion версии {version.version} нет метрики pr_auc")
    return version.version, score


def main() -> dict:
    frame, target, data = load_and_validate(DATA_PATH)
    x_train, x_test, y_train, y_test = train_test_split(
        frame, target, test_size=0.2, stratify=target, random_state=SEED,
    )
    pipeline = build_pipeline(C).fit(x_train, y_train)
    scores = pipeline.predict_proba(x_test)[:, 1]
    pr_auc = float(average_precision_score(y_test, scores))
    roc_auc = float(roc_auc_score(y_test, scores))
    accuracy = float(accuracy_score(y_test, scores >= THRESHOLD))
    matrix = confusion_matrix(y_test, scores >= THRESHOLD, labels=[0, 1])

    metadata = {
        "features": FEATURES,
        "threshold": THRESHOLD,
        "positive_class": "bad",
        "negative_class": "good",
        "target_column": "Risk",
        "source_file": DATA_PATH.name,
        "source_sha256": hashlib.sha256(DATA_PATH.read_bytes()).hexdigest(),
        "sklearn_version": sklearn.__version__,
        "random_state": SEED,
        "train_rows": len(x_train),
        "test_rows": len(x_test),
        "class_counts": data["Risk"].value_counts().to_dict(),
        "missing_values": frame.isna().sum().to_dict(),
        "test_accuracy": accuracy,
        "test_roc_auc": roc_auc,
        "test_pr_auc": pr_auc,
    }

    mlflow.set_experiment(EXPERIMENT)
    client = MlflowClient()
    old_version, old_score = champion_score(client)
    with mlflow.start_run() as run:
        mlflow.log_params({
            "C": C,
            "model": "LogisticRegression",
            "seed": SEED,
            "data": str(DATA_PATH),
            "data_md5": hashlib.md5(DATA_PATH.read_bytes()).hexdigest(),
            "gate_metric": "pr_auc",
            "gate_min_gain": MIN_GAIN,
        })
        mlflow.log_metrics({"pr_auc": pr_auc, "roc_auc": roc_auc, "accuracy": accuracy})
        mlflow.log_dict(metadata, "metadata.json")
        mlflow.log_dict({"labels": ["good", "bad"], "matrix": matrix.tolist()}, "confusion_matrix.json")
        info = mlflow.sklearn.log_model(
            pipeline, name="model", registered_model_name=MODEL_NAME,
            skops_trusted_types=SKOPS_TRUSTED,
        )
        version = info.registered_model_version

    promoted = old_score is None or pr_auc > old_score + MIN_GAIN
    client.set_registered_model_alias(MODEL_NAME, "challenger", version)
    if promoted:
        client.set_registered_model_alias(MODEL_NAME, "champion", version)

    result = {
        "run_id": run.info.run_id,
        "version": version,
        "pr_auc": round(pr_auc, 4),
        "champion_before": old_version,
        "champion_pr_auc_before": old_score,
        "promoted": promoted,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
