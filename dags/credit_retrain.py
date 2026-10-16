"""Проверка данных, обучение и перезапуск credit-service при продвижении модели."""

import time
from datetime import UTC, datetime, timedelta

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.standard.operators.python import PythonOperator, ShortCircuitOperator
from airflow.sdk import DAG, Param
from airflow.timetables.trigger import CronTriggerTimetable
from kubernetes import client, config


def is_promoted(ti) -> bool:
    result = ti.xcom_pull(task_ids="train")
    if not isinstance(result, dict) or type(result.get("promoted")) is not bool:
        raise ValueError("Обучение не вернуло JSON с булевым promoted")
    print(result)
    return result["promoted"]


def restart_service() -> None:
    config.load_incluster_config()
    api = client.AppsV1Api()
    deployment = api.patch_namespaced_deployment(
        name="credit-service", namespace="default",
        body={"spec": {"template": {"metadata": {"annotations": {
            "kubectl.kubernetes.io/restartedAt": datetime.now(UTC).isoformat(),
        }}}}},
        _request_timeout=10,
    )
    generation = deployment.metadata.generation
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        current = api.read_namespaced_deployment("credit-service", "default", _request_timeout=10)
        status = current.status
        desired = current.spec.replicas
        if (
            (status.observed_generation or 0) >= generation
            and status.updated_replicas == desired
            and status.available_replicas == desired
            and status.replicas == desired
        ):
            print(f"credit-service: generation={generation}, ready replicas={desired}")
            return
        time.sleep(2)
    raise TimeoutError("credit-service не завершил rollout за 180 секунд")


with DAG(
    dag_id="credit_retrain",
    description="DVC → Pandera → MLflow gate → rollout credit-service",
    # Учебное расписание: раз в сутки в 03:00 по Москве, без немедленного запуска.
    schedule=CronTriggerTimetable("0 3 * * *", timezone="Europe/Moscow", run_immediately=False),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=20),
    default_args={"retries": 0},
    params={
        "c": Param(1.0, type="number", exclusiveMinimum=0),
        "bad_class_weight": Param(1.0, type="number", exclusiveMinimum=0),
    },
    tags=["credit", "mlops"],
) as dag:
    pod_args = {
        "namespace": "mlops",
        "image": "{{ var.value.credit_image }}",
        "image_pull_policy": "IfNotPresent",
        "in_cluster": True,
        "service_account_name": "airflow",
        "cmds": ["/bin/sh", "-ec"],
        "env_from": [client.V1EnvFromSource(secret_ref=client.V1SecretEnvSource(name="s3-credentials"))],
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://mlflow.mlops:5000",
            "MLFLOW_EXPERIMENT": "german-credit",
            "MODEL_NAME": "german-credit",
            "MLFLOW_DISABLE_AGENT_HINT": "1",
            "MPLBACKEND": "Agg",
            "C": "{{ params.c }}",
            "BAD_CLASS_WEIGHT": "{{ params.bad_class_weight }}",
        },
        "get_logs": True,
        "on_finish_action": "delete_pod",
        "log_events_on_failure": True,
        "startup_timeout_seconds": 300,
        "execution_timeout": timedelta(minutes=10),
    }
    validate = KubernetesPodOperator(
        task_id="validate", name="credit-validate", **pod_args,
        arguments=["uv run --no-sync dvc pull -r cluster\nuv run --no-sync python -m credit_service.data"],
    )
    train = KubernetesPodOperator(
        task_id="train", name="credit-train", **pod_args,
        do_xcom_push=True,
        # читает JSON из /airflow/xcom/return.json
        arguments=[
            "uv run --no-sync dvc pull -r cluster\n"
            "uv run --no-sync python -c 'import json; from pathlib import Path; "
            "from credit_service.train import main; "
            "Path(\"/airflow/xcom/return.json\").write_text(json.dumps(main()))'"
        ],
    )
    promoted = ShortCircuitOperator(task_id="promoted", python_callable=is_promoted)
    rollout = PythonOperator(task_id="rollout", python_callable=restart_service)

    validate >> train >> promoted >> rollout
