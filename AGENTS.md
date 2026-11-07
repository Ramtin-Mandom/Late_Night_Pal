# Hackathon working agreement

## Each task

1. Read `architecture.md` before each prompt. Use its component map to open only the relevant source. If the map is still a template, inspect the entry point and populate the parts you can verify as you work.
2. Make routine design decisions yourself. Build the smallest end-to-end change that satisfies the request. Ask only when the missing decision materially affects the demo.
3. After implementation, review `architecture.md` and `workflow.md`. Update affected sections in the same change. Update the README when setup, commands, or demo steps change. Skip edits to accurate text.

## Component design

Group code by responsibilities that can fail independently. Give each component a clear entry point and understandable inputs and outputs. For example, a data fetcher returns normalized readings, a predictor accepts readings directly, and a UI renders the result. This lets someone try a known reading without a live API or browser.

Use plain values, functions, and existing modules where they suffice. A single temperature reading can live in a variable. A longer, cohesive file is fine. Split a file when the split helps the team change, exercise, or debug a real responsibility. Implement only the current use case. Add CI/CD only on explicit request.

## Verification budget

Use the cheapest meaningful check for the change: one example for logic, one interaction for UI, or one call across a changed component boundary. Reuse existing tests. Add a test when requested or when it cheaply catches a concrete regression. Reserve the full suite for an explicit request or a genuinely broad change. For documentation, check the paths or examples you changed. Benchmarks run on request only. Report the observed result or what prevented verification.

## Commits

Finish the work and verification first. For changes you made, summarize the result and propose one local commit per logical part, with a message and its scope. Include related docs with their feature. Before staging or committing, ask exactly:

Do you want me to commit all proposed changes? (yes/no)

Wait for the reply. On yes, create the proposed commits separately, verify their contents, and report short hashes. On no, leave the edits in place. Preserve teammates’ staged and unstaged changes, including edits in shared files. Avoid blanket staging. Approval covers only the listed local commits. Pushing, publishing, opening a PR, or submitting to the event requires a separate explicit request. Read-only requests do not need a commit question.
