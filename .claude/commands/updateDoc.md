---
description: Sync the README, component map, and application workflow with the code.
disable-model-invocation: true
---

Read `architecture.md`, then inspect `workflow.md`, the README if present, the repository tree, and the relevant entry points and recent edits. Verify descriptions against actual behavior. If the docs are still templates, follow each main execution path to identify the real components.

Update `README.md` with verified setup, launch, and demo instructions. Create it if missing and there is something useful to document. Give each implemented component a section in `architecture.md` with its files, responsibilities, inputs, outputs, and debugging entry point. Trace the user action and data flow in `workflow.md`. Preserve accurate text and unrelated edits. Avoid documenting imagined features or commands.

Check the paths and examples you changed. Summarize any edits and follow the commit approval rule in `AGENTS.md`. If the documents already match the code, report that briefly.
