#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
cluster_name="${KIND_CLUSTER:-mlpro3}"
context_name="kind-${cluster_name}"
started=$SECONDS

for tool in docker kind kubectl helm curl; do
  command -v "$tool" >/dev/null || { echo "Не найдена команда: $tool" >&2; exit 1; }
done
docker info >/dev/null

kube() { kubectl --context "$context_name" --request-timeout=15s "$@"; }

chart_cache="${XDG_CACHE_HOME:-$HOME/.cache}/credit-service/charts"
mkdir -p "$chart_cache"
if command -v sha256sum >/dev/null; then
  checksum() { sha256sum "$1"; }
elif command -v shasum >/dev/null; then
  checksum() { shasum -a 256 "$1"; }
else
  echo "Нужна команда sha256sum или shasum для проверки Helm-архивов" >&2
  exit 1
fi
fetch_chart() {
  local filename="$1" expected="$2" url="$3" actual
  if [[ -f "$chart_cache/$filename" ]]; then
    actual="$(checksum "$chart_cache/$filename")"
    if [[ "${actual%% *}" == "$expected" ]]; then
      return
    fi
  fi
  curl --fail --location --silent --show-error --connect-timeout 10 --max-time 120 \
    --retry 2 --retry-delay 2 --output "$chart_cache/$filename.part" "$url"
  actual="$(checksum "$chart_cache/$filename.part")"
  if [[ "${actual%% *}" != "$expected" ]]; then
    echo "SHA256 архива $filename не совпадает с закреплённым значением" >&2
    return 1
  fi
  mv "$chart_cache/$filename.part" "$chart_cache/$filename"
}

if ! kind get clusters | grep -Fxq "$cluster_name"; then
  kind create cluster --name "$cluster_name" --config platform/kind-config.yaml \
    --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5 \
    --wait 120s
else
  while IFS= read -r node_name; do
    if [[ "$(docker inspect --format '{{.State.Running}}' "$node_name")" != true ]]; then
      docker start "$node_name"
    fi
  done < <(kind get nodes --name "$cluster_name")
fi
kind export kubeconfig --name "$cluster_name"

api_ready=false
for attempt in {1..30}; do
  if kube get --raw=/readyz >/dev/null 2>&1; then
    api_ready=true
    break
  fi
  sleep 2
done
if [[ "$api_ready" != true ]]; then
  echo "Kubernetes API недоступен. Проверьте адрес узла (docker inspect) и маршрут к нему (ip route get)." >&2
  exit 1
fi
kube wait --for=condition=Ready node --all --timeout=120s

for namespace in mlops monitoring traefik; do
  kube create namespace "$namespace" --dry-run=client -o yaml | kube apply -f -
done

fetch_chart traefik-41.6.0.tgz cd7254ea853da73bdb88edc896f079b88d43ffa0bfe699fdbf21081361eac365 \
  https://traefik.github.io/charts/traefik/traefik-41.6.0.tgz
fetch_chart metrics-server-3.14.0.tgz c2ca1185c01e6e7f53dd1b7d131f0c9b3fa50e003ed068b784563a1b5a3422a1 \
  https://github.com/kubernetes-sigs/metrics-server/releases/download/metrics-server-helm-chart-3.14.0/metrics-server-3.14.0.tgz
fetch_chart kube-prometheus-stack-91.5.2.tgz 3e4149116054b2ca0f94f97cfcd703f3d5f780fd6cd94e9c732881826a3ce5cf \
  https://github.com/prometheus-community/helm-charts/releases/download/kube-prometheus-stack-91.5.2/kube-prometheus-stack-91.5.2.tgz

helm upgrade --install traefik "$chart_cache/traefik-41.6.0.tgz" \
  --kube-context "$context_name" -n traefik -f platform/traefik-values.yaml --wait --timeout 5m
helm upgrade --install metrics-server "$chart_cache/metrics-server-3.14.0.tgz" \
  --kube-context "$context_name" -n kube-system -f platform/metrics-server-values.yaml --wait --timeout 5m
helm upgrade --install monitoring "$chart_cache/kube-prometheus-stack-91.5.2.tgz" \
  --kube-context "$context_name" -n monitoring -f platform/monitoring-values.yaml --wait --timeout 10m

# При повторном запуске сохраняем существующий секрет.
if [[ -z "$(kube -n mlops get secret s3-credentials --ignore-not-found -o name)" ]]; then
  kube -n mlops create secret generic s3-credentials \
    --from-literal=AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID:-dvcadmin}" \
    --from-literal=AWS_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY:-dvc-secret-123}" \
    --dry-run=client -o yaml | kube apply -f -
fi

kube apply -f platform/mlflow.yaml -f platform/airflow.yaml -f platform/rustfs.yaml
for deployment in mlflow airflow rustfs; do
  kube -n mlops rollout status "deployment/$deployment" --timeout=300s
done
kube apply -f platform/ingress.yaml

# Перезапускается только Job проверки/создания бакета; существующий бакет не меняется.
kube -n mlops delete job s3-init --ignore-not-found --wait=true
kube apply -f platform/s3-init.yaml
if ! kube -n mlops wait --for=condition=complete job/s3-init --timeout=210s; then
  kube -n mlops logs job/s3-init --all-containers=true
  kube -n mlops get pods -l job-name=s3-init
  exit 1
fi
kube -n mlops logs job/s3-init

for url in \
  http://mlflow.localhost/health \
  http://airflow.localhost/api/v2/monitor/health \
  http://grafana.localhost/api/health \
  http://s3.localhost/health/ready \
  http://s3-console.localhost/rustfs/console/health; do
  echo "Проверка $url"
  curl --noproxy '*.localhost,localhost,127.0.0.1' --fail --silent --show-error \
    --connect-timeout 5 --max-time 15 --retry 5 --retry-delay 2 --retry-all-errors "$url"
  printf '\n'
done
kube get pods -A
echo "Платформа готова за $((SECONDS - started)) с. Бакет: s3://dvc, endpoint: http://s3.localhost"
