"""Измерить чувствительность PR-AUC к разбиению без записи в MLflow.

Конфигурации v3 и v5 взяты из REPORT.md, раздел 2.2.
Правило выбора запаса: диапазон PR-AUC v3, округлённый вверх до сотых,
плюс 0.01. Это консервативная эмпирическая эвристика, не доверительный интервал.
"""

import argparse
import csv
import hashlib
import json
import math
import platform
from pathlib import Path
from statistics import mean, stdev

import sklearn
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split

from credit_service.train import build_pipeline, load_and_validate

CONFIGURATIONS = (("v3", 0.007, 1.0), ("v5", 0.01, 2.0))


def describe(values: list[float]) -> dict:
    return {
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "sample_std": stdev(values),
        "range": max(values) - min(values),
    }


def evaluate(data_path: Path, splits: int) -> tuple[list[dict], dict]:
    frame, target, _ = load_and_validate(data_path)
    data_md5 = hashlib.md5(data_path.read_bytes()).hexdigest()
    rows = []
    for seed in range(splits):
        x_train, x_test, y_train, y_test = train_test_split(
            frame, target, test_size=0.2, stratify=target, random_state=seed,
        )
        for label, c, weight in CONFIGURATIONS:
            pipeline = build_pipeline(c, weight).fit(x_train, y_train)
            scores = pipeline.predict_proba(x_test)[:, 1]
            rows.append({
                "data_md5": data_md5,
                "rows": len(frame),
                "split_seed": seed,
                "configuration": label,
                "C": c,
                "bad_class_weight": weight,
                "train_rows": len(x_train),
                "test_rows": len(x_test),
                "test_bad": int(y_test.sum()),
                "pr_auc": float(average_precision_score(y_test, scores)),
            })
    baseline = [row["pr_auc"] for row in rows if row["configuration"] == "v3"]
    candidate = [row["pr_auc"] for row in rows if row["configuration"] == "v5"]
    deltas = [new - old for old, new in zip(baseline, candidate, strict=True)]
    return rows, {
        "source_path": str(data_path),
        "data_md5": data_md5,
        "rows": len(frame),
        "class_counts": {"bad": int(target.sum()), "good": int((target == 0).sum())},
        "v3": describe(baseline),
        "v5": describe(candidate),
        "paired_v5_minus_v3": describe(deltas),
        "v5_positive_gain_splits": sum(delta > 0 for delta in deltas),
        "seed_42": [row for row in rows if row["split_seed"] == 42],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, nargs="+", required=True)
    parser.add_argument("--splits", type=int, default=50)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/hw3/gate_stability"))
    args = parser.parse_args()
    if args.splits < 2:
        parser.error("--splits должен быть не меньше 2")

    rows, datasets = [], []
    for path in args.data:
        results, summary = evaluate(path, args.splits)
        rows.extend(results)
        datasets.append(summary)

    spread = max(dataset["v3"]["range"] for dataset in datasets)
    min_gain = round(math.ceil(spread * 100) / 100 + 0.01, 2)
    summary = {
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "split_seeds": list(range(args.splits)),
        "test_size": 0.2,
        "stratified": True,
        "model_random_state": 42,
        "metric": "average_precision_score, positive class bad",
        "datasets": datasets,
        "max_v3_range": spread,
        "min_gain_rule": "ceil(max_v3_range * 100) / 100 + 0.01",
        "recommended_min_gain": min_gain,
        "limitations": [
            "Repeated holdouts overlap; these are not independent test samples.",
            "Both training and test samples change; this is split sensitivity, not test-only uncertainty.",
            "The range over these seeds is not a bound for future splits or a significance test.",
            "Paired comparisons apply within one data_md5; cross-version metrics are not directly comparable.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "scores.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
