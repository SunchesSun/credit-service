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
docker compose exec -T db psql -U postgres -d credit -x -c \
  'SELECT request_id, ts, model_version, features, prediction, latency_ms, status_code FROM predictions ORDER BY ts DESC LIMIT 5;'
