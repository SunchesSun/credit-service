#!/usr/bin/env bash
set -euo pipefail

cluster_name="credit-service"
context_name="kind-${cluster_name}"

docker build -t credit-service:1.0 .

if ! kind get clusters | grep -qx "${cluster_name}"; then
  kind create cluster --name "${cluster_name}"
else
  while IFS= read -r node_name; do
    if [[ "$(docker inspect --format '{{.State.Running}}' "${node_name}")" != "true" ]]; then
      docker start "${node_name}"
    fi
  done < <(kind get nodes --name "${cluster_name}")
fi

# A restarted kind node can accept connections before its Kubernetes API is ready.
for attempt in {1..60}; do
  if kubectl --context "${context_name}" get --raw=/readyz >/dev/null 2>&1; then
    break
  fi
  if [[ "${attempt}" -eq 60 ]]; then
    echo "Kubernetes API did not become ready in 120 seconds" >&2
    exit 1
  fi
  sleep 2
done

kubectl --context "${context_name}" wait --for=condition=Ready node --all --timeout=120s
kind load docker-image credit-service:1.0 --name "${cluster_name}"
kubectl --context "${context_name}" apply -f k8s/deployment.yaml -f k8s/service.yaml
kubectl --context "${context_name}" rollout status deployment/credit-service --timeout=120s
kubectl --context "${context_name}" get pods

port_forward_log="$(mktemp)"
kubectl --context "${context_name}" port-forward service/credit-service 8000:80 >"${port_forward_log}" 2>&1 &
port_forward_pid=$!

cleanup() {
  kill "${port_forward_pid}" 2>/dev/null || true
  rm -f "${port_forward_log}"
}
trap cleanup EXIT

curl --fail --silent --show-error \
  --retry 30 --retry-delay 1 --retry-connrefused --retry-all-errors \
  -X POST http://127.0.0.1:8000/v1/predict \
  -H "Content-Type: application/json" \
  --data @good.json
printf '\n'
