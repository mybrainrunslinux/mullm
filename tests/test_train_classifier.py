import json

import pytest

from router.train_classifier import load_samples, main, split_samples


def test_training_dry_run_without_ml_dependencies(tmp_path, capsys):
    data = tmp_path / "data.csv"
    data.write_text("query,category\na,code\nb,code\nc,lookup\nd,lookup\na,code\n")
    main(["--data", str(data), "--output", str(tmp_path / "model"), "--dry-run"])
    report = json.loads(capsys.readouterr().out)
    assert report["train_samples"] == report["validation_samples"] == 2
    assert not (tmp_path / "model").exists()
    samples, _ = load_samples(data, "intent")
    train, heldout = split_samples(samples)
    assert not {s["query"] for s in train} & {s["query"] for s in heldout}


@pytest.mark.parametrize("rows", ["a,code\na,lookup\n", "a,unknown\nb,code\n", "a,code\nb,lookup\n"])
def test_reject_invalid_or_unsplittable_training_data(tmp_path, rows):
    data = tmp_path / "data.csv"
    data.write_text("query,category\n" + rows)
    with pytest.raises(ValueError):
        samples, _ = load_samples(data, "intent")
        split_samples(samples)
