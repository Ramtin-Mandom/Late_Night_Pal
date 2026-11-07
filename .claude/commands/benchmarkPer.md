---
description: Evaluate output quality against known outcomes or expected answers.
argument-hint: "[target, e.g. next-day forecast error]"
disable-model-invocation: true
---

Read `architecture.md`. Evaluate `$ARGUMENTS`, or the main output when omitted. Choose the smallest existing evaluation that answers the question. Select a metric appropriate to the output, such as mean absolute error for numeric predictions or correct cases out of total for a rule engine.

Use existing labeled examples or held-out data. For forecasts, evaluate on observations later than the training observations. Compare to a simple baseline when readily available, such as the last observed value. Report the input source, sample size, metric with units, result, and a meaningful limitation. If labels are missing, explain what remains unmeasurable. Clearly identify illustrative examples.

Keep evaluation lightweight and leave tracked files untouched. Training models, generating large datasets, and optimizing the implementation are separate requests.
