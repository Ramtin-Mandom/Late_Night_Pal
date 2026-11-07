# Late Night Pal

A desktop study sidekick that turns study PDFs into locally compiled study PDFs using Gemini. **Current state (M3):** open a workshop (a local study folder), select PDFs across its subfolders, and generate any of eight study outputs into the folder you're viewing. Each Generate sends one Gemini request, and every PDF is compiled locally with LaTeX. Nothing existing is ever overwritten.

| Output type | Task | Parameters | Result in the current folder |
| --- | --- | --- | --- |
| Study plan | Make schedule | Days, Folder name (default `Study Schedule`) | `Study Schedule/schedule.pdf`, `file-guide.pdf`, `checklist.pdf` |
| Study plan | Make daily study plan | Days, Folder name (default `Daily Study Plan`) | `Daily Study Plan/Day 01/…` through `Day NN/`, each with `notes.pdf`, `sample-questions.pdf`, `checklist.pdf` |
| Single file | Checklist, Notes, Summary, Answer key, One-page cheat sheet, Sample questions | Language style: Technical, Standard or Simple | `checklist.pdf`, `notes.pdf`, `summary.pdf`, `answer-key.pdf`, `cheat-sheet.pdf` (exactly one page), `sample-questions.pdf` |

If a name is taken, the new output gets a suffix: `summary (2).pdf` or `Study Schedule (2)/`.

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
3. Go to the folder where the result should go. Choose an **Output type** and **Task**, then set the Language style (Single file) or Days and an optional Folder name (Study plan). Changing tasks keeps your selection.
4. Click **Generate**. All selected PDFs go to Gemini in one request, and the outputs from the table above are saved in the current folder. The first PDF opens automatically, and **Open document** / **Open output folder** reopen it.

`Sample_pdf\` works as a ready-made workshop. Expect the Gemini request to take most of the time: with two one-page PDFs, Make schedule took about 5 minutes and a two-day daily plan about 7, while local LaTeX took about 2–3 s per PDF. `workflow.md` has the full breakdown.

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
