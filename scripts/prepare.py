"""Настроить локальный DVC, восстановить CSV и создать отсутствующий champion.

Источник, MD5, очистка 1000 → 901 строк и начальный C описаны в REPORT.md.
Существующий изменённый CSV не перезаписывается, гейт обучения не меняется.
"""

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

import mlflow
import pandas as pd
import yaml
from dvc.config import Config
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from credit_service.data import validate_file

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets/german_credit_data.csv"
SOURCE_URL = "https://www.kaggle.com/api/v1/datasets/download/kabure/german-credit-data-with-risk"
SOURCE_MD5 = "3086216ff1ff32f7626554e730cccc91"


def run_dvc(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "dvc", *args], cwd=ROOT, check=True)


def configure_remote() -> None:
    context = "kind-" + os.getenv("KIND_CLUSTER", "mlpro3")
    result = subprocess.check_output([
        "kubectl", "--context", context, "-n", "mlops", "get", "secret", "s3-credentials", "-o", "json",
    ])
    secret = json.loads(result)["data"]
    local = ROOT / ".dvc/config.local"
    local.touch(mode=0o600, exist_ok=True)
    local.chmod(0o600)
    with Config(dvc_dir=str(ROOT / ".dvc")).edit(level="local") as config:
        remote = config.setdefault("remote", {}).setdefault("laptop", {})
        remote["access_key_id"] = base64.b64decode(secret["AWS_ACCESS_KEY_ID"]).decode()
        remote["secret_access_key"] = base64.b64decode(secret["AWS_SECRET_ACCESS_KEY"]).decode()


def reproduce_csv(source: bytes, expected: str) -> bytes:
    if hashlib.md5(source).hexdigest() != SOURCE_MD5:
        raise ValueError("MD5 источника Kaggle изменился; подготовка остановлена")
    frame = pd.read_csv(io.BytesIO(source), index_col=0)
    frame = frame.dropna(subset=["Saving accounts", "Checking account"], how="all")
    # Индекс, NA и LF нужны для побайтного воспроизведения DVC-версии из работы 3.
    content = frame.to_csv(na_rep="NA", lineterminator="\n").encode()
    if hashlib.md5(content).hexdigest() != expected:
        raise ValueError("CSV из Kaggle не соответствует текущему DVC-указателю")
    return content


def check_existing(path: Path, expected: str) -> bool:
    if not path.exists():
        return False
    if hashlib.md5(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"{path}: есть локальные изменения; сохраните их перед запуском")
    return True


def prepare_data() -> None:
    pointer = Path(str(DATA) + ".dvc")
    expected = yaml.safe_load(pointer.read_text())["outs"][0]["md5"]
    if not check_existing(DATA, expected):
        try:
            run_dvc("pull", "-r", "laptop", str(pointer))
        except subprocess.CalledProcessError:
            # Пустой бакет новой установки ещё не содержит версии из указателя.
            # Ошибки S3 не скрываются: последующий обязательный push тоже должен пройти.
            print("DVC pull не выполнен; пробуем воспроизвести CSV из проверенного источника Kaggle.")
            with tempfile.TemporaryDirectory(prefix="credit-data-") as directory:
                archive = Path(directory) / "dataset.zip"
                subprocess.run([
                    "curl", "--fail", "--location", "--retry", "3",
                    "--connect-timeout", "10", "--max-time", "120",
                    SOURCE_URL, "--output", str(archive),
                ], check=True)
                with ZipFile(archive) as zipped:
                    content = reproduce_csv(zipped.read(DATA.name), expected)
                DATA.write_bytes(content)
    check_existing(DATA, expected)
    run_dvc("commit", str(pointer))
    run_dvc("push", "-r", "laptop", str(pointer))


def prepare_model() -> None:
    mlflow.set_tracking_uri("http://mlflow.localhost")
    mlflow.set_experiment("german-credit")
    validate_file(DATA)
    try:
        champion = MlflowClient().get_model_version_by_alias("german-credit", "champion")
    except MlflowException as exc:
        if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
            raise
    else:
        print(f"Сохранён существующий champion v{champion.version}")
        return
    os.environ["MODEL_NAME"] = "german-credit"
    os.environ["MLFLOW_EXPERIMENT"] = "german-credit"
    os.environ.setdefault("C", "0.007")
    from credit_service.train import main

    main()


def main() -> None:
    configure_remote()
    prepare_data()
    prepare_model()


if __name__ == "__main__":
    main()
