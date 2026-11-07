# Late Night Pal

A desktop study sidekick that turns study PDFs into locally compiled study PDFs using Gemini. **Current state (M3):** open a workshop (a local study folder), select PDFs across its subfolders, and generate any of eight study outputs into the folder you're viewing. Each Generate sends one Gemini request, and every PDF is compiled locally with LaTeX. Nothing existing is ever overwritten.

| Output type | Task | Parameters | Result in the current folder |
| --- | --- | --- | --- |
| Study plan | Make schedule | Days, Folder name (default `Study Schedule`) | `Study Schedule/schedule.pdf`, `file-guide.pdf`, `checklist.pdf` |
| Study plan | Make daily study plan | Days, Folder name (default `Daily Study Plan`) | `Daily Study Plan/Day 01/…` through `Day NN/`, each with `notes.pdf`, `sample-questions.pdf`, `checklist.pdf` |
| Single file | Checklist, Notes, Summary, Answer key, One-page cheat sheet, Sample questions | Language style: Technical, Standard or Simple | `checklist.pdf`, `notes.pdf`, `summary.pdf`, `answer-key.pdf`, `cheat-sheet.pdf` (exactly one page), `sample-questions.pdf` |

If a name is taken, the new output gets a suffix: `summary (2).pdf` or `Study Schedule (2)/`. Days can be any positive whole number; the app never shortens a plan.

**Inputs:** PDF, PPTX, DOCX, TXT and Markdown. With **Efficient** off, PDFs are sent to Gemini as they are, while PPTX and DOCX are converted to text locally (the status line says so). TXT and MD always go as text. With **Efficient** on, every file is converted to text locally first, keeping page and slide numbers. That can be cheaper, but diagrams, equations, tables and formatting may be lost. Conversions are cached in `%LOCALAPPDATA%\late_night_workshop\conversions\`. If a PDF looks scanned (little or no text), the app asks whether to **Process original** (send that file as is) or **Cancel** (nothing is sent).

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
2. Click a folder to open it, and use **Up** to go back. Click a PDF, PPTX, DOCX, TXT or MD file to select it: it turns blue and appears under **Selected Inputs** with its workshop-relative path. Click it again to deselect. The selection stays as you move between folders.
3. Go to the folder where the result should go. Optionally tick **Efficient**. Choose an **Output type** and **Task**, then set the Language style (Single file) or Days and an optional Folder name (Study plan). Changing tasks keeps your selection.
4. Click **Generate**. All selected files go to Gemini in one request, and the outputs from the table above are saved in the current folder. The first PDF opens automatically, and **Open document** / **Open output folder** reopen it.

If something fails, the status line says which stage failed, what to do next, and that nothing was saved. Your selection and settings stay, so you can just click **Generate** again. LaTeX logs for compile failures are saved in `%LOCALAPPDATA%\late_night_workshop\logs\`.

`Sample_pdf\` works as a ready-made workshop. Expect the Gemini request to take most of the time: with two one-page PDFs, Make schedule took about 5 minutes and a two-day daily plan about 7, while local LaTeX took about 2–3 s per PDF. `workflow.md` has the full breakdown.

Headless checks:

```powershell
.venv\Scripts\python -m late_night_workshop --check                          # resources + LaTeX, no API call
.venv\Scripts\python -m late_night_workshop --summarize Sample_pdf\Note_1.pdf  # one real API call -> Sample_pdf\summary.pdf
```

## Windows handoff build

**Verified on:** Windows 10 Home 22H2 (10.0.19045, 64-bit), with MiKTeX `lualatex` on PATH, on 2026-11-07. The ZIP was extracted to a fresh folder with spaces in its name, outside the checkout, and launched from an unrelated folder without the dev venv. The packaged exe was operated through Windows UI Automation: native Create/Open Workshop dialogs, Recents, then Summary of `Lectures\photosynthesis-lecture.pdf`. It wrote `Revision\summary.pdf` in 218 s (almost all of it Gemini), opened it in the default PDF viewer, and Open output folder opened Explorer on `Revision`.

Build from the repository root (about 1½ minutes):

```powershell
.venv\Scripts\python -m pip install -e ".[build]"
.venv\Scripts\python packaging\build_release.py
```

- **Share:** `dist\LateNightPal-win64.zip` (about 75 MB).
- **After extracting, launch:** `Late Night Pal\Late Night Pal.exe`. No Python installation is needed.
- The ZIP contains `Late Night Pal.exe`, `_internal\` (Qt, Python and the bundled prompts and templates), `Demo\Biology Demo Workshop\`, `Demo\Example output\M6 Daily Study Plan (pre-fix)\`, `.env.example` and `READ ME FIRST.txt`.
- The build script refuses to zip `.env` files, logs, caches, `recents.json`, or any file containing the developer's key. It also keeps every path inside the ZIP under 150 characters, because Windows limits full paths to 260.

**On the receiving PC:**

1. Install [MiKTeX](https://miktex.org/download) and make sure `lualatex` is on PATH. Compile something once so MiKTeX finishes installing its packages and fonts before the demo.
2. Extract the ZIP anywhere. A short path such as `C:\Demo` is safest.
3. Provide the Gemini key at runtime: copy `.env.example` to `.env` next to `Late Night Pal.exe` and fill in `GEMINI_API_KEY`, or set the `GEMINI_API_KEY` environment variable. A `.env` in the current working directory also works. The key is never bundled.
4. Optional preflight from PowerShell in the extracted folder: `& ".\Late Night Pal.exe" --check`. It lists the 14 bundled resources, `lualatex`, whether a key was found (never the key itself), and `frozen build: True`. `--extract <file>` prints what local conversion produces for a PDF, PPTX, DOCX, TXT or MD file.

The executable is windowed. Command-line modes print to the PowerShell window they were started from.

## Demo sequence (rehearsed 2026-11-07)

The demo workshop is `Demo\Biology Demo Workshop\` in the ZIP, or `demo\Biology Demo Workshop\` in the repository:

- `Lectures\photosynthesis-lecture.pdf` is a text PDF about photosynthesis.
- `Labs\osmosis-lab-scan.pdf` is an image-only scanned osmosis lab. Its unique fact is that potato strips in **0.8 M sucrose lost 14% of their mass**, and the cells are isotonic with about 0.4 M sucrose.
- `Revision\` is empty, ready for output.

**Before each run, copy `Biology Demo Workshop` to a fresh place** (for example your Desktop) and open that copy. The original stays clean, and every run starts with an empty `Revision\`.

1. Launch `Late Night Pal.exe` (or `.venv\Scripts\python -m late_night_workshop` from the repository). Click **Open Workshop** and choose your fresh copy. Later you can reopen it from **Recent Workshops**.
2. Click `[folder] Lectures` → `photosynthesis-lecture.pdf`, **Up**, `[folder] Labs` → `osmosis-lab-scan.pdf`, **Up**, `[folder] Revision`. **Selected Inputs** shows both relative paths.
3. Choose **Output type: Study plan**, **Task: Make daily study plan**, **Days: 2**, leave **Folder name** empty, and tick **Efficient**. Click **Generate**.
4. A dialog says `Labs/osmosis-lab-scan.pdf (page 1) has little or no extractable text…`. Click **Process original**.
5. While Gemini works (about 2 minutes in the rehearsal; earlier runs took up to 7), open the labelled example `Example output\M6 Daily Study Plan (pre-fix)\Day 01\notes.pdf`. It was built from the scan and states the 0.8 M → −14% result, and its subtitle reads `From Labs/osmosis-lab-scan.pdf`. It is the M6 rehearsal output from **before the answer-label fix**, so its *Answers* sections lack `Q1`/`Q2` labels; fresh runs label them.
6. When the status shows `Saved 6 PDFs in …\Revision\Daily Study Plan`, `Day 01\notes.pdf` opens automatically. Use **Open output folder** to show `Day 01\` and `Day 02\`, each with `notes.pdf`, `sample-questions.pdf` and `checklist.pdf`.

**Quick single-file demo** (verified from the packaged build): on a fresh copy, select only `Lectures\photosynthesis-lecture.pdf`, open `Revision`, choose **Single file → Summary**, then **Generate**. The result is `Revision\summary.pdf`.
