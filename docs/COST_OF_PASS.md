# Cost-of-Pass

Cost-of-Pass measures how much money and time it takes to get one accepted
answer, not just whether a model can eventually solve a task.

For PR-Gauntlet, report:

- score: solved issues / total issues
- total provider spend across all attempts
- cost per solved issue: total spend / solved issues
- wall time per solved issue
- retries, escalations, and failed branches per solved issue

For a 110/110 run, the headline number is:

```text
Cost-of-Pass = total_run_cost_usd / 110
```

For muPatch, use the same accounting but make the unit "accepted patch":
include generated candidates, tool calls, local test runs, cloud escalations,
and rejected patches. Do not hide failed attempts; they are part of the real
cost of getting a usable fix.

This framing lets muLLM, OmniRoute, and combined muLLM+OmniRoute runs be
compared on dollars-per-accepted-result, latency-per-accepted-result, and
quality at equal budget, instead of only pass rate.
