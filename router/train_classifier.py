"""Offline training for local Transformers sequence classifiers.

Run python -m router.train_classifier --help. Model files must already be local;
this command never downloads models or executes model-provided Python code.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from router.models import IntentCategory


def load_samples(path: Path, mode: str) -> tuple[list[dict], list[str]]:
    labels = ["local", "cloud"] if mode == "binary" else sorted(c.value for c in IntentCategory)
    samples, seen = [], {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not {"query", "category"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires query,category columns")
        for line, row in enumerate(reader, 2):
            query, category = row["query"].strip(), row["category"].strip().lower()
            if not query or category not in labels:
                raise ValueError(f"Invalid query/category at line {line}")
            key = " ".join(query.lower().split())
            if key in seen:
                if seen[key] != category:
                    raise ValueError(f"Conflicting labels at line {line}")
                continue
            seen[key] = category
            samples.append({"query": query, "label": labels.index(category)})
    if len({s["label"] for s in samples}) < 2:
        raise ValueError("Training requires at least two classes")
    return samples, labels


def split_samples(samples: list[dict], seed: int = 42) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    train, validation = [], []
    for label in sorted({s["label"] for s in samples}):
        group = [s for s in samples if s["label"] == label]
        if len(group) < 2:
            raise ValueError("Each represented class needs at least two unique queries")
        rng.shuffle(group)
        count = max(1, len(group) // 5)
        validation.extend(group[:count])
        train.extend(group[count:])
    rng.shuffle(train)
    return train, validation


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-model", type=Path)
    parser.add_argument("--mode", choices=("intent", "binary"), default="intent")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    samples, labels = load_samples(args.data, args.mode)
    train, validation = split_samples(samples)
    report = {"train_samples": len(train), "validation_samples": len(validation), "labels": labels}
    if args.dry_run:
        print(json.dumps(report, sort_keys=True))
        return
    if not args.base_model or not args.base_model.is_dir():
        parser.error("--base-model must be a local Transformers sequence-classifier directory")
    if args.epochs < 1:
        parser.error("--epochs must be positive")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be empty; evaluate a new candidate before replacing production")
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.manual_seed(42)
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, local_files_only=True, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model, num_labels=len(labels), local_files_only=True,
        trust_remote_code=False, use_safetensors=True, ignore_mismatched_sizes=True,
        id2label=dict(enumerate(labels)), label2id={v: k for k, v in enumerate(labels)},
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5)
    model.train()
    for _ in range(args.epochs):
        for start in range(0, len(train), 8):
            batch = train[start:start + 8]
            inputs = tokenizer([s["query"] for s in batch], padding=True, truncation=True,
                               max_length=128, return_tensors="pt")
            optimizer.zero_grad()
            loss = model(**inputs, labels=torch.tensor([s["label"] for s in batch])).loss
            loss.backward()
            optimizer.step()
    model.eval()
    correct = 0
    with torch.no_grad():
        for sample in validation:
            inputs = tokenizer(sample["query"], truncation=True, max_length=128, return_tensors="pt")
            correct += int(model(**inputs).logits.argmax(-1).item() == sample["label"])
    report["validation_accuracy"] = correct / len(validation)
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    (args.output / "mullm_label_map.json").write_text(json.dumps({"id2label": dict(enumerate(labels))}))
    (args.output / "training_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
