# CSV to JSON

Requires Python 3.11 or newer. No packages or API keys are needed to run the
generated converter.

```sh
python convert.py input.csv output.json
```

CSV headers become JSON keys; values remain strings. Invalid input reports an
error and leaves the output untouched. See contract.md for the exact behavior.

Factory generates convert.py, runs independent acceptance checks, and packages
dist/csv-json.zip. This starter requires a local model to generate code. It has
no human checkpoints: success delivers the package; exhausted repairs fail.
