# CSV to JSON contract

Invocation: `python convert.py input.csv output.json`.

Use Python 3.11+ standard library only. Read UTF-8 CSV, accepting a leading BOM.
The first row supplies object keys. Preserve their spelling and order; reject
empty/whitespace-only or duplicate keys. Preserve all values as strings,
including empty strings, leading zeros, Unicode, quoted commas and newlines.
Each subsequent row must have exactly as many cells as the header.
A header-only file produces an empty array. An empty file is invalid.

On success write a UTF-8 JSON array of objects and exit 0. Output must be stable
across repeated conversions. Do not access the network or invoke subprocesses.
On malformed CSV (including unclosed quotes), invalid headers, wrong row width,
missing input, or invalid arguments: write a useful error to stderr and exit
nonzero. Validate before opening output: invalid input must not change an
existing output file or create a new one. Input and output must be different files.
