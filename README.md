# Late Night Pal

A desktop study sidekick that turns study PDFs into locally compiled study PDFs using Gemini. **Current state (M1):** pick one PDF, get a Gemini summary compiled to PDF with local LaTeX, and open it.

## Prerequisites (Windows)

- Python 3.11+
- [MiKTeX](https://miktex.org/download) with `lualatex` on PATH. The app checks for it before making any API call.
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)

## Setup

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[build]"
```

Put the key in `.env` at the repository root (git ignores this file):

```text
GEMINI_API_KEY=your-key-here
# optional; default is gemini-3.8-flash
# GEMINI_MODEL=gemini-3.8-flash
```

A `GEMINI_API_KEY` environment variable works too.

## Run

```powershell
.venv\Scripts\python -m late_night_workshop
```

Click **Choose PDF...**, pick a PDF (for example `Sample_pdf\Note_1.pdf`), then click **Generate summary**. The summary is saved next to the source as `<name> summary.pdf`, or `<name> summary (2).pdf` if that name is taken. It opens automatically when done. A 35-page PDF took about 3 minutes.

Headless checks:

```powershell
.venv\Scripts\python -m late_night_workshop --check                          # resources + LaTeX, no API call
.venv\Scripts\python -m late_night_workshop --summarize Sample_pdf\Note_1.pdf  # one real API call
```

## Packaging probe (full packaging is M7)

```powershell
.venv\Scripts\python -m PyInstaller packaging\late-night-workshop.spec --noconfirm
& "dist\Late Night Pal\Late Night Pal.exe" --check
```

The executable doesn't include the API key. Run it from a folder that has a `.env`, or set `GEMINI_API_KEY`. LaTeX must be installed on the machine.
