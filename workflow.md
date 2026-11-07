# Application workflow

Current state: M1. The only user action is summarizing one PDF. Component names match `architecture.md`.

## Summarize one PDF

Example: the user picks `Sample_pdf/Note_1.pdf` (35-page statistics notes).

1. **Desktop UI.** `ui.run_app()` window → **Choose PDF...** opens a file dialog filtered to `*.pdf`; the path is shown and **Generate summary** becomes enabled.
2. **Generate summary** disables both buttons and starts `Worker.run()` on a `QThread`, calling `ui.summarize_file(path, on_progress)`. Progress messages appear in the status label.
3. **Renderer preflight.** `rendering.check_runtime()` looks for `lualatex`. If it's missing, the job stops with `missing_latex` and install guidance **before any Gemini call**.
4. The output path is chosen next to the source: `Sample_pdf/Note_1 summary.pdf`, or `Note_1 summary (2).pdf` if that already exists.
5. **Gemini client.** `gemini_client.summarize_pdf()` loads `./.env` if present, sends the PDF inline with `prompts/summary.md` to `gemini-3.8-flash` (or `GEMINI_MODEL`) via the Interactions API, and parses JSON `{title, blocks}`. Quota, auth, model, network and malformed-response failures become short `GeminiError` messages without the key.
6. **Renderer.** `render_document()` escapes every string, fills `templates/document.tex`, compiles with `lualatex` in a temp folder, and copies the PDF out with exclusive create.
7. **Desktop UI.** The status label shows `Saved: <path>`, the PDF opens in the default viewer, and **Open summary PDF** reopens it. On failure the status shows `Error: ...`, and the selected file stays selected for a retry.

Observed for this example: about 3 min 14 s end to end, producing a 3-page PDF.

The headless equivalent of steps 3–6 is `python -m late_night_workshop --summarize <file.pdf>`.
