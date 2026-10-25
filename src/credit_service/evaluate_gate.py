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

from credit_service.train import MIN_GAIN, TEST_SIZE, build_pipeline, load_and_validate, should_promote

CONFIGURATIONS = (("v3", 0.007, 1.0), ("v5", 0.01, 2.0))


def describe(values: list[float]) -> dict:
    return {
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "sample_std": stdev(values),
        "range": max(values) - min(values),
    }


def evaluate(data_path: Path, splits: int, min_gain: float = MIN_GAIN) -> tuple[list[dict], dict]:
    frame, target, _ = load_and_validate(data_path)
    data_md5 = hashlib.md5(data_path.read_bytes()).hexdigest()
    rows = []
    for seed in range(splits):
        x_train, x_test, y_train, y_test = train_test_split(
            frame, target, test_size=TEST_SIZE, stratify=target, random_state=seed,
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
        "v5_passes_gate_splits": sum(should_promote(new, old, min_gain) for old, new in zip(baseline, candidate, strict=True)),
        "seed_42": [row for row in rows if row["split_seed"] == 42],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, nargs="+", required=True)
    parser.add_argument("--splits", type=int, default=50)
    parser.add_argument("--min-gain", type=float, default=MIN_GAIN)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.splits < 2:
        parser.error("--splits должен быть не меньше 2")
    if not math.isfinite(args.min_gain) or not 0 <= args.min_gain < 1:
        parser.error("--min-gain должен быть конечным числом в [0, 1)")

    rows, datasets = [], []
    for path in args.data:
        results, summary = evaluate(path, args.splits, args.min_gain)
        rows.extend(results)
        datasets.append(summary)

    summary = {
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "split_seeds": list(range(args.splits)),
        "test_size": TEST_SIZE,
        "stratified": True,
        "model_random_state": 42,
        "metric": "average_precision_score, positive class bad",
        "datasets": datasets,
        "gate_policy": {
            "min_gain": args.min_gain,
            "rule": "candidate_pr_auc > champion_pr_auc + min_gain",
            "basis": "Engineering tolerance for absolute PR-AUC improvement; not estimated from split variability.",
        },
        "limitations": [
            "Repeated holdouts overlap; these are not independent test samples.",
            "Both training and test samples change; this is split sensitivity, not test-only uncertainty.",
            "The range over these seeds is not a bound for future splits or a significance test.",
            "Paired comparisons apply within one data_md5; cross-version metrics are not directly comparable.",
            "Passing the fixed margin on one split does not establish statistical significance.",
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
