#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  docker compose down
}
trap cleanup EXIT

docker compose up -d --build
curl --fail --silent --show-error \
  --retry 30 --retry-delay 1 --retry-connrefused --retry-all-errors \
  http://127.0.0.1:8000/ready
printf '\n'
curl --fail --silent --show-error \
  -X POST http://127.0.0.1:8000/v1/predict \
  -H "Content-Type: application/json" \
  --data @good.json
printf '\n'
validation_response="$(curl --silent --show-error \
  -X POST http://127.0.0.1:8000/v1/predict \
  -H "Content-Type: application/json" \
  --data '{"age":0}' \
  --write-out $'\n%{http_code}')"
validation_body="${validation_response%$'\n'*}"
validation_status="${validation_response##*$'\n'}"
printf '%s\nHTTP %s\n' "${validation_body}" "${validation_status}"
if [[ "${validation_status}" != "422" ]]; then
  echo "Expected validation response 422, got ${validation_status}" >&2
  exit 1
fi
docker compose exec -T db psql -U postgres -d credit -x -c \
  'SELECT request_id, ts, model_version, features, prediction, latency_ms, status_code FROM predictions ORDER BY ts DESC LIMIT 5;'
