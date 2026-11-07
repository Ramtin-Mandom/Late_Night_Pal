---
description: Measure startup, interaction, or request timing for the current app.
argument-hint: "[target, e.g. click Predict to visible result]"
disable-model-invocation: true
---

Read `architecture.md`. The optional target is `$ARGUMENTS`. If omitted, measure one or two user-visible timings on the main demo path.

Define the start and end events. Use an existing timer, browser tools, or a small temporary measurement. For a click, time through the visible result if possible. Label server-only timing explicitly. Prefer a handful of repeat runs, separate cold and warm results when relevant, and avoid expensive load tests.

Report what ran, the environment, the run count, timings with units, and a median when useful. If the target cannot be measured here, explain the missing prerequisite. Keep the command read-only with respect to tracked files. Implement optimizations only on request.
