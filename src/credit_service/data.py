"""
MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m credit_service.data
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path

import mlflow
import pandas as pd
import pandera.pandas as pa


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

# Категории и допустимые пропуски 
ROW_SCHEMA = pa.DataFrameSchema({
    "record_id": pa.Column(int, pa.Check.ge(0), unique=True, required=False),
    "age": pa.Column(int, pa.Check.in_range(19, 75)),
    "sex": pa.Column(str, pa.Check.isin(["female", "male"])),
    "job": pa.Column(int, pa.Check.in_range(0, 3)),
    "housing": pa.Column(str, pa.Check.isin(["free", "own", "rent"])),
    "saving_accounts": pa.Column(str, pa.Check.isin(["little", "moderate", "quite rich", "rich"]), nullable=True),
    "checking_account": pa.Column(str, pa.Check.isin(["little", "moderate", "rich"]), nullable=True),
    "credit_amount": pa.Column(float, pa.Check.in_range(250, 18424), coerce=True),
    "duration": pa.Column(int, pa.Check.in_range(4, 72)),
    "purpose": pa.Column(str, pa.Check.isin([
        "business", "car", "domestic appliances", "education", "furniture/equipment",
        "radio/TV", "repairs", "vacation/others",
    ])),
    "risk": pa.Column(str, pa.Check.isin(["good", "bad"])),
}, strict=True, name="credit_rows")

# выгрузка: не более 20% потери от исходных 1000 строк;
# bad = 30% ±5 п.п., обе версии (30% и 32.30%) проходят
MIN_ROWS = 800
BAD_SHARE_MIN = 0.25
BAD_SHARE_MAX = 0.35
BATCH_SCHEMA = pa.DataFrameSchema(
    {"risk": pa.Column(str)},
    checks=[
        pa.Check(lambda frame: len(frame) >= MIN_ROWS, name="minimum_rows"),
        pa.Check(lambda frame: BAD_SHARE_MIN <= frame["risk"].eq("bad").mean() <= BAD_SHARE_MAX, name="bad_share"),
    ],
    name="credit_batch",
)

VALIDATION_ERRORS = (pa.errors.SchemaErrors, pa.errors.SchemaError, ValueError, OSError)


def clean_data(raw: pd.DataFrame) -> pd.DataFrame:
    """Переименовать столбцы без удаления строк и заполнения пропусков."""
    return raw.rename(columns={**COLUMNS, "Risk": "risk", "Unnamed: 0": "record_id"})


def validate_data(frame: pd.DataFrame) -> pd.DataFrame:
    validated = ROW_SCHEMA.validate(frame, lazy=True)
    return BATCH_SCHEMA.validate(validated, lazy=True)


def validate_file(path: Path) -> str:
    """Создать MLflow run; ошибки схемы сохранить и пробросить для кода выхода 1."""
    with mlflow.start_run(run_name="validate", tags={"task": "validate", "valid": "false"}) as run:
        print(json.dumps({"run_id": run.info.run_id, "data": str(path)}, ensure_ascii=False))
        mlflow.log_params({
            "data": str(path), "min_rows": MIN_ROWS,
            "bad_share_min": BAD_SHARE_MIN, "bad_share_max": BAD_SHARE_MAX,
        })
        try:
            content = path.read_bytes()
            mlflow.log_param("data_md5", hashlib.md5(content).hexdigest())
            frame = clean_data(pd.read_csv(io.BytesIO(content)))
            mlflow.log_metric("rows", len(frame))
            validated = validate_data(frame)
        except VALIDATION_ERRORS as exc:
            failures = getattr(exc, "failure_cases", None)
            if not isinstance(failures, pd.DataFrame):
                failures = pd.DataFrame([{"check": "read_csv", "failure_case": str(exc)}])
            mlflow.log_text(failures.to_csv(index=False), "failure_cases.csv")
            mlflow.log_metric("failure_count", len(failures))
            raise
        mlflow.log_metric("bad_share", validated["risk"].eq("bad").mean())
        mlflow.set_tag("valid", "true")
        return run.info.run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(os.getenv("DATA_PATH", "datasets/german_credit_data.csv")))
    parser.add_argument("--experiment", default=os.getenv("MLFLOW_EXPERIMENT", "german-credit"))
    args = parser.parse_args(argv)
    mlflow.set_experiment(args.experiment)
    try:
        run_id = validate_file(args.data)
    except VALIDATION_ERRORS:
        print(json.dumps({"valid": False, "artifact": "failure_cases.csv"}))
        return 1
    print(json.dumps({"run_id": run_id, "valid": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
