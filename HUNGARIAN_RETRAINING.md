# Hungarian Classifier Retraining

The current seed file is `scripts/training_data_sample.csv`. It contains 110
labeled prompts across English and Hungarian, with the columns:

- `query`
- `category`

This is enough for a smoke test, regression check, and first retraining pass. It
is not enough by itself to claim robust multilingual generalization. Treat it as
an answer key for finding obvious misroutes before expanding to a larger held-out
set.

## Current muLLM1 Baseline

Generate a human-review CSV:

```bash
.venv-mullm1/bin/python scripts/eval_classifier_csv.py \
  --csv scripts/training_data_sample.csv \
  --write-predictions benchmarks/hungarian_training_sample_mullm1_predictions.csv
```

Baseline result from the rule-first refactor:

- 110 rows total
- 38.2% category accuracy
- 63.2% English category accuracy
- 25.0% Hungarian category accuracy

That is a useful failure signal: the refactor runs, but the current classifier
rules do not preserve the multilingual behavior we want. The annotated CSV adds
these columns for review:

- `mullm1_language`
- `mullm1_category`
- `mullm1_category_ok`
- `mullm1_complexity`
- `mullm1_tier`
- `mullm1_confidence`

If we add `complexity`, `tier`, `expected_complexity`, or `expected_tier` columns
to the source CSV, the evaluator will score those too.

## Validate Training Data Without Heavy Dependencies

The retraining script can validate the CSV on a lean install:

```bash
.venv-mullm1/bin/python scripts/retrain_classifier.py \
  --data scripts/training_data_sample.csv \
  --dry-run
```

This should not require Torch, Transformers, or Datasets. A real training run
still requires:

```bash
pip install transformers datasets torch accelerate
```

## First Training Command

For the Windows 8GB VRAM path, start with the multilingual base model already
configured in the script:

```bash
python scripts/retrain_classifier.py \
  --data scripts/training_data_sample.csv \
  --output ~/.mullm/models/routing-classifier-multilingual \
  --epochs 8 \
  --batch-size 8 \
  --fp16
```

Use `--no-cuda` for CPU-only validation. The script refuses to overwrite an
existing model unless `--force` is supplied.

## Translation Sanity Check

A separate translation smoke exists for checking representative pairs:

```bash
bash scripts/translation-smoke.sh
```

The goal is not every language pair. The useful smoke is:

- English to Hungarian
- Hungarian to English
- Hungarian to another non-English language

