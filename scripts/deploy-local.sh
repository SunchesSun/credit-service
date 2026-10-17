#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
cluster_name="${KIND_CLUSTER:-mlpro3}"
context_name="kind-$cluster_name"
image="credit-service:local-$(date +%s)"
kube() { kubectl --context "$context_name" "$@"; }

# Существующий пароль не меняем. Для новой учебной базы используется postgres.
if [[ -z "$(kube get secret credit-secrets --ignore-not-found -o name)" ]]; then
  kube create secret generic credit-secrets --from-literal=POSTGRES_PASSWORD=postgres --from-literal=DATABASE_URL=postgresql://postgres:postgres@postgres:5432/credit
fi
kube apply -f k8s/postgres.yaml
kube rollout status deploy/postgres --timeout=180s

docker buildx build --load -t "$image" .
kind load docker-image "$image" --name "$cluster_name"
kube apply -f k8s/configmap.yaml -f k8s/service.yaml -f k8s/ingress.yaml -f k8s/hpa.yaml
kubectl set image --local -f k8s/deployment.yaml api="$image" -o yaml | kube apply -f -
kube rollout status deploy/credit-service --timeout=180s
kube apply -f k8s/servicemonitor.yaml -f k8s/dashboard.yaml
kube create configmap airflow-dags -n mlops --from-file=dags/credit_retrain.py --dry-run=client -o yaml | kube apply -f -
kube exec -n mlops deploy/airflow -- airflow variables set credit_image "$image"

curl --noproxy '*' --fail --silent --show-error --retry 5 --retry-all-errors http://credit.localhost/health
echo
curl --noproxy '*' --fail --silent --show-error -H 'Content-Type: application/json' -d @good.json http://credit.localhost/v1/predict
echo
curl --noproxy '*' --fail --silent --show-error http://credit.localhost/metrics | grep '^credit_model_info{'
kube get pods -A
