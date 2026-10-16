"""Трафик через Ingress: выборки реальных признаков из DVC CSV, без Risk и индекса."""

import argparse
import json
import random
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import pandas as pd

from credit_service.data import COLUMNS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://credit.localhost")
    parser.add_argument("--data", type=Path, default=Path("datasets/german_credit_data.csv"))
    parser.add_argument("--duration", type=float, default=180)
    parser.add_argument("--rps", type=float, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not 0 < args.rps < float("inf") or not 0 < args.duration < float("inf"):
        parser.error("duration и rps должны быть конечными положительными числами")

    frame = pd.read_csv(args.data)[list(COLUMNS)].rename(columns=COLUMNS)
    records = frame.astype(object).where(frame.notna(), None).to_dict("records")
    if not records:
        parser.error("CSV пуст")
    randomizer = random.Random(args.seed)
    # Запросы к локальному Ingress не должны уходить в прокси хоста.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    deadline = started + args.duration
    requests = errors = 0
    versions = Counter()
    while time.monotonic() < deadline:
        tick = time.monotonic()
        request = urllib.request.Request(
            args.host.rstrip("/") + "/v1/predict",
            data=json.dumps(randomizer.choice(records), allow_nan=False).encode(),
            headers={"Content-Type": "application/json"},
        )
        requests += 1
        try:
            with opener.open(request, timeout=5) as response:
                body = json.load(response)
                if response.status != 200 or not 0 <= body["score"] <= 1:
                    raise ValueError("Неверный ответ predict")
            versions[body["model_version"]] += 1
            print(json.dumps({
                "status": 200, "model_version": body["model_version"],
                "latency_ms": round((time.monotonic() - tick) * 1000, 2),
            }), flush=True)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            errors += 1
            print(json.dumps({"error": str(exc)}), flush=True)
        time.sleep(max(0, min(deadline - time.monotonic(), tick + 1 / args.rps - time.monotonic())))
    print(json.dumps({
        "requests": requests, "errors": errors, "model_versions": dict(versions),
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }), flush=True)
    return int(errors > 0)


if __name__ == "__main__":
    raise SystemExit(main())
