# Late Night Pal

A desktop study sidekick that turns study PDFs into locally compiled study PDFs using Gemini. **Current state (M2):** open a workshop (a local study folder), select PDFs across its subfolders, and generate one combined Summary PDF into the folder you're viewing. It's compiled locally with LaTeX and never overwrites an existing file.

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

Demo flow:

1. On the start screen, click **Open Workshop** (or **Create Workshop**) and choose a folder. Recent Workshops are remembered in `%LOCALAPPDATA%\late_night_workshop\recents.json`.
2. Click a folder to open it, and use **Up** to go back. Click a PDF to select it: it turns blue and appears under **Selected Inputs** with its workshop-relative path. Click it again to deselect. The selection stays as you move between folders.
3. Go to the folder where the result should go, keep **Single file → Summary**, and click **Generate**.
4. All selected PDFs are sent to Gemini in one request. The result is saved as `summary.pdf` in the current folder, or `summary (2).pdf`, `summary (3).pdf`, and so on if that name is taken. It opens automatically, and **Open document** / **Open output folder** reopen it.

`Sample_pdf\` works as a ready-made workshop. A 35-page PDF took about 3 minutes in M1.

Headless checks:

```powershell
.venv\Scripts\python -m late_night_workshop --check                          # resources + LaTeX, no API call
.venv\Scripts\python -m late_night_workshop --summarize Sample_pdf\Note_1.pdf  # one real API call -> Sample_pdf\summary.pdf
```

## Packaging probe (full packaging is M7)

```powershell
.venv\Scripts\python -m PyInstaller packaging\late-night-workshop.spec --noconfirm
& "dist\Late Night Pal\Late Night Pal.exe" --check
```

The executable doesn't include the API key. Run it from a folder that has a `.env`, or set `GEMINI_API_KEY`. LaTeX must be installed on the machine.
