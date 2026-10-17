#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
repo_url="${1:-$(git remote get-url origin)}"
repo_url="${repo_url%.git}"

if docker container inspect gh-runner >/dev/null 2>&1; then
  docker start gh-runner >/dev/null
else
  docker run -d --name gh-runner --network kind --group-add "$(stat -c '%g' /var/run/docker.sock)" -v /var/run/docker.sock:/var/run/docker.sock --entrypoint /bin/bash ghcr.io/actions/actions-runner:2.337.0 -lc 'sleep infinity'
fi
if ! docker exec gh-runner test -f /home/runner/.runner; then
  read -r -s -p 'Registration token из GitHub Settings → Actions → Runners: ' runner_token
  echo
  [[ -n "$runner_token" ]] || { echo "Токен не указан" >&2; exit 1; }
  docker exec gh-runner /home/runner/config.sh --url "$repo_url" --token "$runner_token" --name "credit-kind-$(date +%s)" --labels kind --unattended
  unset runner_token
fi
if ! docker exec -i gh-runner python3 - <<'PY'
from pathlib import Path
import sys

for path in Path("/proc").glob("[0-9]*/comm"):
    try:
        if path.read_text().strip() == "Runner.Listener":
            sys.exit(0)
    except FileNotFoundError:
        pass
sys.exit(1)
PY
then
  docker exec -d gh-runner /home/runner/run.sh
fi
echo "Runner запущен или уже работал. Проверь статус Online в GitHub."
