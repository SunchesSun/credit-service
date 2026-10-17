#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
started=$SECONDS

for tool in docker uv kind kubectl helm curl; do
  command -v "$tool" >/dev/null || { echo "Не найдена команда: $tool" >&2; exit 1; }
done
docker info >/dev/null
docker buildx version >/dev/null
uv sync --frozen --python 3.11

# На этой установке Python не разрешал *.localhost: причина описана в REPORT.md.
if ! uv run --no-sync python - <<'PY'
import socket
import sys

names = ("s3", "s3-console", "mlflow", "airflow", "grafana", "credit")
try:
    ready = all(socket.gethostbyname(f"{name}.localhost") == "127.0.0.1" for name in names)
except OSError:
    ready = False
sys.exit(0 if ready else 1)
PY
then
  hosts_entry="127.0.0.1 s3.localhost s3-console.localhost mlflow.localhost airflow.localhost grafana.localhost credit.localhost"
  echo "Добавление локальных имён в /etc/hosts; может потребоваться пароль sudo."
  if [[ $EUID -eq 0 ]]; then
    echo "$hosts_entry" >> /etc/hosts
  else
    echo "$hosts_entry" | sudo tee -a /etc/hosts >/dev/null
  fi
fi

export NO_PROXY="${NO_PROXY:+$NO_PROXY,}localhost,127.0.0.1,.localhost"
export no_proxy="${no_proxy:+$no_proxy,}localhost,127.0.0.1,.localhost"
export MLFLOW_TRACKING_URI=http://mlflow.localhost
export MLFLOW_DISABLE_AGENT_HINT=1

bash platform/up.sh
uv run --no-sync python scripts/prepare.py
bash scripts/deploy-local.sh
echo "Запуск завершён за $((SECONDS - started)) с. API: http://credit.localhost/docs"
