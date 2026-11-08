# Late Night Pal — UI/UX Design Specification

Planning snapshot: 2026-11-07. This document specifies a future visual redesign; it implements nothing. Only `design.md` is authored for this task. No new assets are necessary.

## 1. Executive Design Vision

Build a calm, moonlit desktop workspace: deep navy canvas, clearly separated blue surfaces, readable blue-white text, restrained amber details, and one obvious primary action. Keep study files central and generation settings understandable. The visual identity comes from the existing artwork, especially `icons/illustrations/welcome-desk.svg` and the 29 outline icons in `icons/ui/`.

The primary journey is **Open/Create Workshop → browse and select → choose operation → review destination and settings → Generate → understand progress → open results**. File organization joins that journey only when its functional implementation is complete. The redesign must preserve request snapshots, filesystem contracts, processing, validation, outputs, automatic first-document opening, and error recovery.

Priority vocabulary throughout this document:

- **Required:** needed for a coherent, accessible redesign and faithful presentation of existing behavior.
- **Recommended:** meaningful usability gain with modest UI work.
- **Optional:** skip when time is limited; never a dependency for core polish.

Scope: **two existing main screens and seven dialog types visible in source**, with generation/result states and the Organize mode within the workshop. Five dialog types belong to the established generation workflow; two organizer dialog types appeared in concurrently developing source. Two additional documented surfaces receive conditional designs: Recent downloads and Name tags. Eight UI milestones follow functional completion; each is gated by the controls actually available at that time.

## 2. Existing Application UI Audit

### Inspection basis and implementation status

Inspected `architecture.md`, `components.md`, `workflow.md`, `README.md`, `PHASE_2_PROJECT_MAP_AND_MILESTONES.md`, `src/late_night_workshop/ui.py`, `src/late_night_workshop/__main__.py`, `src/late_night_workshop/__init__.py`, `pyproject.toml`, and every SVG plus `icons/preview.html`. No existing design or theme file was found. Source is the authority when historical planning text differs.

Framework: Python 3.11+, **PySide6 Qt Widgets**, `QMainWindow`, two pages in a `QStackedWidget`, `QVBoxLayout`/`QHBoxLayout`, `QListWidget`, native inputs and dialogs. `Window`, `Worker`, and the newly developing `OrganizeWorker` are local classes inside `ui.run_app()`. The workshop also has a nested mode stack and checkable mode buttons. Generation already uses a `QThread`; worker decisions return to the UI thread. There is no web frontend, CSS framework, QML scene, global application stylesheet, sidebar, settings page, integrated PDF viewer, or results library.

This is a **source-based UI audit**. The application was not launched or screenshot-tested during this planning task, avoiding recents/cache writes and API activity. Layout risks below are inferred from widget construction, not asserted as reproduced screenshots. The SVG geometry, colors, and illustration contents were inspected; their prior asset review does not establish current application appearance.

| Area | Exists now | Under development / documented next | Redesign boundary |
|---|---|---|---|
| Start | Welcome label, recent list, Open/Create buttons; `show_start()` | No new start workflow specified | Restyle/recompose existing controls |
| Workshop | Back, root/current paths, Up/Refresh, checkbox+name browser rows, Selected Inputs/Remove, modes, task form, eligibility note, status, output buttons | P2-M2 is now recorded complete in component docs | Preserve explicit checkbox selection and folder-name navigation |
| Generation | Make me mode; eight tasks, conditional parameters, Efficient, scan decisions, stage messages, success/error/cancel states | Further visual polish only | No new task, API, output type, estimator, or general Cancel |
| Organization | Organize mode/six buttons; newest source wires five basic actions through `organize`, `OrganizeWorker`, `organize_finished`, and executor/outcome code | P2-M3 code is actively changing and not runtime-verified here; Super Wrap remains disabled/pending P2-M4 | Source presence is not acceptance; style completed contracts only |
| Downloads | `downloads.py` Chrome record provider/probe; `components.md` records P2-M1 feasibility pass | One-hour filtering, tray/import UI in P2-M6 | Provider is not evidence of a working tray |
| Name tags | Documented contract only | Folder chips/counters, persistence/drop rename in P2-M5 | No current tag screen or persistence UI |
| Output access | Status text, first PDF auto-opens, Open document/Open output folder | No separate results screen specified | Keep access in workshop, render returned paths |
| Settings | Environment/.env setup in README and error guidance | No settings interface specified | Do not add a settings destination or credential editor |

`README.md` still introduces M3 while architecture/workflow describe M7; Phase 2's original plan still calls Chrome feasibility unverified while `components.md` records a pass. During this task P2-M2 landed and the source advanced into P2-M3 while component documentation still described those five actions as pending. These are snapshot/documentation differences, not demonstrated runtime defects. The refreshed source inspection below supersedes the initial M1-only view; recheck the component guide and source again before implementation. Do not edit those documents as part of this design task.

### Findings

P1 = address early in redesign; P2 = normal milestone work; P3 = optional polish. No critical data-loss defect was demonstrated by this inspection.

| Classification / component | Current problem and source evidence | Proposed improvement | Priority | Implementation complexity |
|---|---|---|---|---|
| Critical usability | None verified; no runtime/destructive operation audit performed | Retain functional safety checks; do not claim new defects | — | — |
| Usability / recent keyboard | Start page connects recents through `itemClicked`; no explicit recent-item activation equivalent. Browser now has native checkbox/name-button controls | Wire recent activation through the same existing route; verify keyboard traversal and focus after row rebuild | P1 | Low–medium |
| Usability / destination | `folder_lbl` says Current folder, while `generate()` captures it as output destination; no destination cue beside Generate | Read-only “Save to” cue derived from the same current folder | P1 | Low |
| Usability / selected paths | P2-M2 now supplies per-entry Remove and folder/missing prefixes, using row widgets and full relative labels | Preserve accessible Remove behavior; improve long-path layout and target sizing | P2 | Low |
| Usability / progress and results | One wrapping `QLabel` contains every stage, errors, warnings and potentially 3 × Days output paths | Separate persistent progress/result presentation with scrollable details | P1 | Medium |
| Usability / error location | `invalid_parameter` copy refers to a highlighted setting, but `generate()` only sets status text | Mark the corresponding field when the existing error identifies it; retain general error when ambiguous | P1 | Low |
| Major visual / theme | No global palette; selected files hard-code blue/white, grey text uses two other greys | One shared palette and semantic state styling | P1 | Medium |
| Major visual / hierarchy | Start title alone has explicit typography; form and results share one right `QVBoxLayout` | Consistent heading hierarchy and bounded sections | P2 | Low–medium |
| Major visual / assets | Browser uses literal `[folder]`; no SVG resource wiring in `ui.py`; current package data excludes icons | Integrate existing local icons and future packaged resource mapping | P2 | Medium |
| Major visual / resize risk | Initial 900 × 600; body ratio 3:2; no explicit minimum, splitter, path elision or form scroll area | Flexible browser + bounded right panel with scrolling; verify actual clipping later | P1 | Medium |
| Minor polish / empty list | `show_start()` inserts “No recent workshops yet.” as a list item; browser has no designed empty state | Non-actionable empty panel with short next step | P2 | Low |
| Minor polish / disabled help | P2-M2 now supplies red eligibility/blocker labels; empty-selection/busy Generate reasons remain implicit | Reuse existing eligibility text, use semantic error tokens, add presentation-only empty/busy reasons | P2 | Low |
| Major visual / Organize | Concurrent P2-M3 lays six commands in one horizontal row; confirmations use generic Ok/Cancel and truncate preview to 15 entries | Two-column labelled action grid; descriptive confirmation label; bounded scrollable full scope | P1 | Low–medium |
| Optional enhancement | No hover transitions or illustration integration | Short state transitions, limited welcome/empty artwork | P3 | Low |

## 3. Visual Identity and Design Principles

**Required:** navy and muted blue establish depth; typography and spacing provide hierarchy. Amber appears in the artwork and occasional informational emphasis, never on every button. Blue remains the action/selection family. Error, warning and success colors carry semantic meaning alongside text and symbols.

Use flat surfaces with subtle borders. No glass blur, neon outlines, animated backgrounds, large ornamental dashboards, or gradient buttons. Keep the OS title bar and standard window controls. Main panels have the same radius; smaller controls use the smaller radius. Avoid nested cards around individual form fields.

Show artwork only on welcome and genuinely empty views. A busy workshop contains files and controls, not decorative illustrations. A folder stays a folder; the download tray never uses the wastebasket icon. “Remove from selection” never looks like Delete.

Keep **Organize** and **Make me** as the existing mode labels. Preserve **Rip** and its helper: “Move each selected folder’s contents up one level.” Keep original task labels and supported parameter values. Use short sentences in sentence case. Never advertise AI cost, completion time, token usage or a percentage unsupported by the actual event/result contract.

## 4. Complete Color Palette and Semantic Tokens

All values below are opaque sRGB HEX. Token names are specification names, not a requirement for a new token framework. Implement with a small Python mapping and derived QPalette/QSS. Do not scatter raw colors across handlers.

| Semantic token | HEX | Use |
|---|---|---|
| `bg.app` | `#101F36` | Main canvas |
| `bg.navigation` | `#0D1A2D` | Header/navigation strip; optional local rail only |
| `surface.primary` | `#142842` | Browser, form and primary panels |
| `surface.secondary` | `#1A314F` | Inputs, inset status/details areas |
| `surface.elevated` | `#203A58` | Menus, tooltips, app-owned dialogs |
| `border.subtle` | `#304864` | Decorative panel edges and dividers |
| `border.control` | `#6C86A4` | Interactive input/button boundaries and unchecked selection boxes |
| `text.primary` | `#DCE9FA` | Body, filenames, headings, button labels, default icons |
| `text.secondary` | `#B9CCE2` | Supporting content, path detail |
| `text.muted` | `#93ACC9` | Captions and nonessential metadata |
| `text.disabled` | `#7487A0` | Inactive controls only; never necessary instructions |
| `accent.primary` | `#8CB9ED` | Selected marker, informational emphasis, progress fill |
| `accent.secondary` | `#E9B86D` | Restrained amber motif; occasional warm detail |
| `action.primary` | `#315E88` | Primary button background, with `text.primary` |
| `action.primary.hover` | `#37658F` | Primary button hover |
| `action.primary.pressed` | `#294F75` | Primary button press |
| `state.hover` | `#203D5E` | Neutral row/button hover |
| `state.pressed` | `#294C70` | Neutral press |
| `state.selected` | `#25466A` | Checked rows and current mode |
| `state.selected.hover` | `#2B5076` | Hover on persistent selected item |
| `state.disabled` | `#182A41` | Disabled control background |
| `focus.ring` | `#B3D4FF` | 2 DIP focus perimeter |
| `status.success` | `#A3D8BA` | Success text/indicator |
| `status.success.bg` | `#173D35` | Success notice |
| `status.warning` | `#E9B86D` | Warning text/indicator; aliases secondary accent |
| `status.warning.bg` | `#43351F` | Warning notice |
| `status.error` | `#F3A5AF` | Error text, destructive outline/label |
| `status.error.bg` | `#452C3B` | Error notice/destructive hover |
| `status.error.pressed` | `#563244` | Destructive pressed background |
| `status.info` | `#A6CAEF` | Information text/indicator |
| `status.info.bg` | `#1C3857` | Information notice |
| `progress.track` | `#304864` | Progress track; aliases subtle border |
| `progress.fill` | `#8CB9ED` | Progress fill; aliases primary accent |
| `shadow.color` | `#000000` | Dialog shadow only, 25% opacity |

State precedence: disabled suppresses hover/pressed; focus is an additional perimeter; selected+hover uses its own token; invalid input keeps its error border on hover/focus, with focus perimeter still visible. Status panels use the matching status background, status-color icon, and `text.primary` message. Do not use border.subtle alone to communicate an input boundary or selected state.

Calculated contrast examples using WCAG relative luminance: primary text on primary surface **12.10:1**; muted text on that surface **6.36:1**; primary text on primary action **5.53:1**, hover **4.99:1**; primary text on selected row **7.90:1**; control border against primary surface **3.95:1**; focus against selected row **6.37:1**; amber on primary surface **8.17:1**. These are token calculations, not a claim that the unimplemented UI passes accessibility. Verify remaining enabled-control/status combinations in UI-M1 and UI-M8. Target ≥4.5:1 for normal text, ≥3:1 for large text and meaningful control/focus graphics.

**Required governance:** new UI colors need an existing semantic role or an explicitly documented token addition. Illustration-internal colors remain authored artwork, not UI tokens. Do not recolor originals on disk. Native OS dialogs/title bars may follow the OS palette. Under Windows high-contrast mode, prioritize system colors and standard focus/selection over the custom theme.

## 5. Typography System

Use the installed **Segoe UI** family on Windows, with Segoe UI Variable as an optional available-family preference, then Noto Sans and the platform sans-serif. Do not download or bundle a font. Resolve available families at runtime and keep font selection in shared presentation setup. Technical text uses Cascadia Mono → Consolas → platform monospace.

Sizes below are **logical pixels/DIP**, not points; 14 DIP ≈10.5 pt at 96 DPI. Use font metrics and minimum heights, avoiding clipped ascenders or fixed-height multiline labels. Nominal line heights are layout targets; Qt labels do not accept browser CSS line-height.

| Role | Size / weight | Nominal line height | Use |
|---|---|---|---|
| Application title | 24 / 600 | 32 | Welcome product heading |
| Page heading | 20 / 600 | 28 | Workshop name/start section |
| Section heading | 16 / 600 | 24 | Selected Inputs, Make me, Recent Workshops |
| Card heading | 14 / 600 | 20 | Result/progress heading |
| Body | 14 / 400 | 20 | Instructions and dialog body |
| Supporting | 13 / 400 | 20 | Efficient explanation, full path line |
| Caption | 12 / 400 | 16 | File type, completion-time metadata |
| Button | 14 / 600 | 20 | All action labels |
| File name | 14 / 400; selected 500 | 20 | Browser; selection/result rows |
| Technical information | 12 / 400 mono | 18 | Log path, error code, diagnostic detail |
| Status label | 13 / 600 | 20 | Stage, Success, Failed, Waiting for you |

Keep body content in sentence case. Do not uppercase all section labels. Preserve filename case, underscores, extensions and user-supplied names exactly in displayed values. Use larger headings, spacing and weight to separate sections; do not bold the whole form. When the OS uses enlarged fonts, allow fields/rows/dialogs to grow and retain their content.

## 6. Spacing, Geometry, and Elevation

Use DIP throughout. Spacing scale: **4, 8, 12, 16, 24, 32, 40, 48**. Two-pixel values are permitted for borders/focus, not general layout spacing.

| Element | Required specification |
|---|---|
| Page | 24 padding, 24 section gap; compact mode 16 padding/16 gap |
| Panels/cards | 16 internal padding; 12 internal subsection gaps; 16 between adjacent panels |
| Forms | 4 label-to-control; 12 between field groups; 8 control-to-help; 16 before action footer |
| Header/navigation | 56 minimum height; 16 horizontal padding; 8 between controls |
| Folder toolbar | 44 minimum height; Up + path + Refresh when available; 8 gaps |
| Primary/secondary button | 40 minimum height; 16 horizontal padding; 8 icon-to-label gap; minimum width 96 when labelled |
| Icon-only button | 36 × 36 target, 20 icon; dense remove target 32 × 32, 16 icon |
| Input/select/spin box | 40 minimum height; 12 horizontal content padding; 8 between adjoining controls |
| File row | 44 minimum; 12 horizontal inset; 8 checkbox/icon/name gaps |
| Two-line recent/selected row | 56 minimum; 8 vertical inset; path below filename |
| Mode selector | 40 high segments; 8 icon-to-label; 4 inner frame padding |
| Dialog | 24 padding; 16 content gaps; 24 before button row; 8 between buttons |
| Tag chip | 36 minimum height; 8 internal gaps; wrap at 8 horizontal/vertical spacing |
| Local navigation rail | Not used in baseline; if future completed shell already has one, 176–200 expanded, 56 collapsed, 44 navigation rows; no new destinations |

Radius tokens: control **8**, panel/dialog **12**, badge/chip **8**. Avoid pills except genuinely circular status glyphs. Borders: **1** normal, **2** focus or critical state. Keep component outer sizes stable when border states change. Selection additionally shows a check or 3-DIP inset marker; no meaning relies on border color alone.

Elevation: E0 canvas; E1 panels differentiated by surface/border; E2 popup/dialog. No shadows on every row/card. App-owned floating dialogs may use 16-DIP blur, vertical offset 4, zero horizontal offset, black 25%; use `QGraphicsDropShadowEffect` only if it does not conflict with native framing/performance. OS-owned windows retain their own shadows.

Scrollbars: 12-DIP interactive track, minimum 32-DIP thumb, 6 radius, `border.control` thumb on `surface.primary`, `text.muted` thumb on hover. Keep controls discoverable; no hover-only scroll affordance. Splitter handle 8 DIP with visible 1-DIP central divider; keyboard resizing or a usable default layout must remain available.

Icon default **20 DIP**, principal action/task icons **24 DIP**, dense control glyph **16 DIP**. Existing art is authored on 24 × 24 with 1.8-unit round strokes; use 24 for the four priority organizer icons. Keep the glyph smaller than its target. Illustrations preserve aspect ratio with no stretching/cropping.

## 7. Application Layout and Navigation

### Main shell

Retain `QMainWindow` and `QStackedWidget`. No new dashboard, global sidebar, tabs for imaginary pages, or separate document editor. The workshop has a slim header and two responsibility-based columns. The **right column is the action panel, not a navigation sidebar**.

```text
OS title bar: Late Night Pal
Header: [Workshops]   Workshop name                 workshop path
┌─────────────────────────────────┬─────────────────────────────┐
│ [Up] Current folder [Refresh]    │ Selected Inputs (n)         │
│ Browser                         │ relative paths [Remove]     │
│ file/folder rows                ├─────────────────────────────┤
│                                 │ [Organize | Make me]        │
│                                 │ Output type / Task          │
│                                 │ task-specific parameters    │
│                                 │ Efficient + visible note    │
│ [Recent downloads*]              │ Save to: Revision           │
│ Name tags*                       │ [Generate]                  │
└─────────────────────────────────┴─────────────────────────────┘
Right-panel continuation: progress / result / error + output buttons
* Only when the corresponding Phase 2 functionality exists.
```

**Required:** header Back remains “Workshops”; workshop name is emphasized, absolute root secondary. Folder toolbar gives current relative path, not a second equally prominent absolute root. Display `/` or “Workshop root” consistently at root. Up remains disabled there. Breadcrumb-like text is acceptable, but do not make path segments clickable without an existing navigation route; Up and folder navigation suffice.

At normal width use a horizontal `QSplitter`: browser takes the flexible remainder; right panel defaults to 376 DIP, range 336–440. The browser should usually receive ≥440 DIP. Inside the right panel, Selected Inputs is bounded and independently scrollable; the task form scrolls when necessary, while Save to and Generate remain in its footer. Progress/result details have their own bounded expansion area. Avoid three simultaneously tiny scroll regions: at short height collapse optional result detail first, then cap Selected Inputs at 120–160 DIP, leaving form scrolling usable.

Navigation does not clear selection. Switching existing task/output type retains the current functional parameter behavior; do not invent cross-task persistence the code does not provide. Mode switching preserves P2-M2's selection and parameter behavior. Do not redirect an active job when the browsed folder changes. During a job show the captured destination in its progress card; before the next job show the current destination.

**Recommended:** no prominent action above file browsing except workshop navigation. Make me has one filled primary action, Generate. Organize's six direct commands are neutral outlined buttons, with Delete separated and destructive styled. Native folder pickers remain native.

## 8. Screen-by-Screen Design Specifications

Global component states in §9 apply to every view below. Shared colors, type and spacing reference §§4–6; exceptions are explicit. Counts distinguish pages, dialog types and embedded workflow states.

### 8.1 Existing screen 1 — `Window._start_page()` / `show_start()`

- **Purpose/current:** open/create a workshop or reopen a recent. Currently a welcome label, large recent list and bottom Open/Create row.
- **Weakness:** no visual grouping/empty treatment, full paths dominate, title styling is isolated.
- **Proposed hierarchy:** centered container, maximum 1040 DIP; welcome heading and one sentence; two action buttons; Recent Workshops list below. At ≥1040 window width a 300 × 200 welcome illustration sits to the heading's right, with the content column taking the remainder. Artwork is decorative, never interactive.
- **Presentation:** `bg.app` canvas, `surface.primary` recent panel, application-title typography, 24 gaps. Recent row: folder icon 20, folder basename 14, parent path 13 secondary; minimum 56 high. Open Workshop is primary, Create Workshop secondary, aligned at the same height with 12 gap.
- **States:** hover highlights recent row; keyboard current row gets focus ring independently of activation. No persistent “selected workshop” status after navigation. Empty: “Open a folder to start a workshop.” with Open/Create retained; no clickable dummy list row. Missing recent: warning glyph + “Folder unavailable” metadata, still actionable through existing dialog. Loading only if actual work is pending; no invented splash delay. Errors use existing dialogs.
- **Navigation/resize:** recent activation reuses `open_recent`; folder picking and create sequence unchanged. Hide illustration first below 1040; a single content column and scrollable recents remain at minimum size. Restore keyboard focus to initiating control after cancelled dialogs.
- **Future files:** `src/late_night_workshop/ui.py` (`_start_page`, `show_start`, `open_recent`); shared presentation module proposed in §14; artwork mapping §10.

### 8.2 Existing screen 2 — `Window._workshop_page()`

- **Purpose/current:** navigate workshop, select inputs, choose Organize/Make me, configure task, generate and access outputs. Current top root/back row; 3:2 browser/action columns; Selected Inputs above mode buttons/nested stack; status below stack and output buttons inside Make me.
- **Weakness:** destination semantics are indirect, no shared style, long status/paths compete with the form, explicit sizing constraints absent.
- **Hierarchy/layout:** shell in §7. Browser section heading may be “Files”; right panel uses Selected Inputs → mode → operation configuration → Save to/action → feedback. Retain the current explicit instruction in concise visible text: “Tick to select a file or folder. Open a folder by its name.” Make me's eligibility note separately lists supported types. Preserve folder-name navigation and checkbox selection; file-name activation also toggles as it does now.
- **Presentation:** primary surfaces on app background; section headings 16/600; filenames 14; path/helper 13. Browser panel padding 8 around full-width rows; toolbar/control spacing per §6. No alternating stripes needed. Use folder.svg instead of `[folder]`; generic input files retain filename/extension and may use a platform document icon, never an unrelated study-output icon.
- **Selected state:** canonical workshop selection drives row background/check and count, not `QListWidget` transient highlight. Browsing focus has its own ring. Selected Inputs shows workshop-relative path, retains the extension, and scrolls at 160-DIP typical height. P2-M2 remove control has accessible name “Remove <relative path> from selection”; never delete.
- **Task form:** keep Output type then Task. Single file shows Language style (Technical/Standard/Simple); Study plan shows Days and optional Folder name with registry default as placeholder. Days retains positive-integer range, default 2, no new product cap. Efficient is a normal checkbox, off initially, with the complete existing explanation visible beneath it in 13-DIP supporting text. Do not hide its tradeoff solely in a tooltip.
- **Action:** show “Save to: <workshop-relative current folder>” above Generate. Preserve output names/default folder behavior. Generate is disabled for empty selection, blockers or active generation/organization; show “Select at least one supported file.” or a truthful busy reason. Use `make_me_status` and the existing eligibility/blocker content for missing, folder, unsupported or unreadable entries. Do not silently drop inputs.
- **Empty:** centered `empty-workshop.svg` at 144 × 144, heading “This folder is empty”, helper “Choose files from another folder, or add files here and refresh.” Empty current folder does not disable generation with valid cross-folder selections. Empty Selected Inputs is compact text, not another large illustration.
- **Errors/loading:** browser navigation errors stay near the browser; generation feedback uses §8.3. Hover rows use state.hover; unsupported generation entries use disabled treatment plus text tooltip. No fake browser-loading animation for synchronous local listing.
- **Navigation/resize:** Back/Up semantics unchanged. Long root/path labels elide, full values available as tooltip and accessible description. Follow §12 splitter/scroll behavior. Do not add a mobile navigation mode.
- **Future files:** `src/late_night_workshop/ui.py` (`_workshop_page`, `refresh`, `refresh_selected`, `toggle`, `open_folder`, `remove_selected`, `refresh_clicked`, `mode_changed`, `go_up`, `task_changed`, `current_parameters`); `workshops.py`/`tasks.py` contracts are read-only dependencies for visual implementation. Preserve `later()`'s deferred rebuild after clicked row widgets emit signals.

### 8.3 Existing workshop states — generation, cancellation, results and errors

These are states of screen 2, not additional pages or a job-history system. Existing entry points: `generate`, `describe_progress`, `choose_for`, `job_finished`, `describe_error`, `open_document`, `open_output_folder` in `src/late_night_workshop/ui.py`.

| State | Hierarchy / content | Interaction and appearance |
|---|---|---|
| Idle | Destination cue; Generate; latest result only when `last_paths` still permits access | No spinner; disabled reason visible when needed |
| Starting/Preparing | Progress heading; existing message; captured destination | loading.svg 20; indeterminate progress; Generate disabled |
| Waiting for you | “Waiting for you”; scan explanation dialog | warning/info visual; stop spinner; never imply work continues while waiting |
| Gemini | Existing stage label/message plus “This can take a few minutes.” | Indeterminate; no ETA or fake percent; no general Cancel control |
| Checking | Existing checking/repair message | Same progress card, stable height; announce repair only when event says so |
| Rendering | Render message including document count/name when supplied | Keep count as text; progress stays indeterminate while Worker exposes strings, rather than parse strings into a made-up percentage |
| Saving | Existing publication message | Keep output buttons unavailable until success |
| Success | success.svg + “Saved <n> PDF(s)”; actual output root; relative-path details; warnings below | Success notice, count 14/600; path details bounded at 200 DIP and scrollable; Open document + Open output folder 40 high |
| Cancelled by scan decision | “Cancelled. Nothing was sent to Gemini or saved.” | Neutral information state; no failure styling; Generate re-enabled |
| Generation error | Existing stage + message, “Nothing was saved…” guarantee, existing next step; optional LaTeX log path | Error notice; warning.svg with explicit “Failed” text; diagnostics selectable, scrollable; selection/settings retained |

Do not remove existing automatic opening of the first returned PDF. Open document continues to open that first file; Open output folder uses returned output root. A displayed result list is read-only presentation, not a new per-document opening contract or embedded viewer. Do not guess filenames from the task settings. Large daily plans must not expand the window beyond its available geometry.

Render notices as plain text; filenames, error messages and logs must not be interpreted as rich-text markup. Form validation messages appear directly below their known field (12/13 DIP, status.error) plus summary when needed. If no reliable field association exists, show a general error rather than highlighting a guessed field. Keep a last result visually subordinate once a new job clears `last_paths`; unavailable buttons must never point to stale paths.

### 8.4 Existing dialog type 1 — folder picker (`ask_folder`)

**Purpose/current:** `QFileDialog.getExistingDirectory` for Open Workshop or choosing Create Workshop's parent. Native folder navigation is already appropriate; do not replace it with a themed in-app explorer. **Proposed:** retain native layout, OS typography/colors/hover/selection/error feedback and native resize behavior; use the existing precise captions. Parent it to the main window; center/position through the OS within the active screen. Native loading states stay OS-owned. Cancel returns unchanged to the initiating button. Empty folder contents do not imply invalidity. No custom illustration. Future file: `src/late_night_workshop/ui.py`, `ask_folder`, `open_workshop_dialog`, `create_workshop_dialog`.

### 8.5 Existing dialog type 2 — Create Workshop name (`ask_name`)

**Current:** native `QInputDialog.getText`, label “Workshop folder name:”, returns stripped name or empty. **Weakness:** ungrouped/default styling relative to the future shell. **Proposed hierarchy:** title → visible label → existing text input → existing accept/cancel buttons. App-owned surface.elevated, title 16/600, body 14, 24 padding, 16 gaps; width 440 preferred, minimum 360 where screen permits. folder.svg 24 optional beside title. Retain current validation and return semantics; do not invent live rules that differ from `create_workshop`. Field hover/focus/disabled per §9; initial text is empty; no loading spinner for name entry. On failure use existing creation error dialog; do not claim folder creation happened. Escape/Cancel leaves state intact, Enter invokes existing acceptance. Dialog wraps labels and caps width to available screen. Future file: `src/late_night_workshop/ui.py`, `ask_name`.

### 8.6 Existing dialog type 3 — Workshop not found (`open_recent`)

**Current:** warning `QMessageBox` with missing path, Open another folder, Remove from list, Cancel. **Weakness:** long absolute path may dominate. **Proposed:** warning.svg 24 + heading; explanation “This workshop folder no longer exists.”; selectable wrapped path; action row preserving all three outcomes. Width 480 preferred, 560 maximum, 24 padding, 16 body gaps, standard 40-high buttons. Use warning panel/status colors and body/supporting type; no artwork/loading. Open another folder is primary, Cancel neutral, Remove from list destructive outline with helper “Removes this recent entry only.” Missing is a state, not a disabled unclickable recent row. Keep focus on safe Cancel initially; deletion of actual files is never implied. Scroll long body content and wrap path at separators. Future file: `src/late_night_workshop/ui.py`, `open_recent`; keep the original dialog-to-action mapping.

### 8.7 Existing dialog type 4 — Create Workshop failure (`create_workshop_dialog`)

**Current:** `QMessageBox.warning` shows a workshop/filesystem error. **Proposed:** shared failure dialog, status.error background strip, warning.svg with explicit “Couldn’t create workshop”, existing sanitized message as plain selectable text, existing acknowledgment action. Width 480 preferred/max 560, 24 padding, body 14/20; 16 gaps; no selected/empty/loading state, only standard button hover/press/focus. Do not fabricate retry or credentials/settings links. Dismiss returns to existing flow; does not automatically repeat creation. Allow scrolling for large error bodies and clamp to active screen. Future file: `src/late_night_workshop/ui.py`, `create_workshop_dialog`.

### 8.8 Existing dialog type 5 — Little text found (`choose_for` / `answer_decisions`)

**Purpose/current:** one scan/no-text source decision at a time, including affected pages/slides, Process original or Cancel; UI-thread dialog answers worker. **Weakness:** long source/page information shares the message block.

**Proposed hierarchy:** warning.svg 24 + “Little text found”; relative source path in a distinct supporting line; affected units wrapped below; unchanged explanation of original transmission; Process original and Cancel. Use elevated surface and warning accent, title 16/600, body 14, 24 padding and 16 gaps, preferred width 520/max 600. Process original is primary, Cancel secondary; initial focus is Cancel so accepting transmission is deliberate. Preserve existing button result mapping and all-decisions-before-send behavior. A long affected-page list scrolls; do not remove identifying units. Waiting is a static state, not a running spinner. No “skip this file”, OCR option, or later-stage cancellation. Escape/close is Cancel; restore prior focus after resolution. Future file: `src/late_night_workshop/ui.py`, `choose_for`, `answer_decisions`, `Worker.decide`; preserve UI-thread/Event handoff.

### 8.9 Existing mode under active development — Organize panel

**Status at refreshed inspection:** mode and shared selection are implemented (P2-M2). Concurrent source now wires Delete, Rip, Wrap, Copy and Paste through planning, confirmations, threaded execution, reconciliation and `describe_outcomes`; this P2-M3 work was not runtime-verified here and docs had not yet caught up. Super Wrap remains visibly disabled with `SUPER_WRAP_PENDING`. Design acceptance for each action waits for its functional acceptance, not just source presence. Current layout puts the six actions in one horizontal row; redesign that row, not the underlying execution.

In the right action panel place Organize/Make me segments below shared Selected Inputs. The left browser, downloads button and name tags remain visible across mode changes. Use organize.svg/make-me.svg at 20; selected segment has state.selected + marker + accessible checked state. Keep a stable panel width to avoid browser reflow on each switch.

Use a two-column action grid, 12 gaps, 44-high buttons, icons 24 and labels 14/600: row 1 Wrap / Rip; row 2 Super Wrap / Copy; row 3 Paste / Delete. All six commands stay direct, with Delete visually separated by a top divider/8 extra gap inside its cell and destructive treatment. If 2-column labels cannot fit at enlarged text, stack buttons; do not shorten Super Wrap to an ambiguous symbol. Show Rip's exact helper directly below the grid. Keep destination visible for destination-based commands; clarify Rip uses each selected folder's own parent.

Use existing eligibility results for disabled reasons: no selection, no folders for Rip, no file-list clipboard for Paste, unavailable recycling, conflicting running action. Show the reason in text on focus/hover and in a compact helper when it blocks the main intended action. Do not add polling to update clipboard/download state. Loading uses actual executor messages; never “saved nothing” after partial mutation.

**Dialog type 6 — Wrap name:** the developing `organize('wrap')` already uses `QInputDialog.getText` labelled “New folder name (created in the current folder):”. It inherits §8.5 geometry/type/states, with explicit captured destination and move semantics. Preserve its existing accepted/cancelled name handling and planner validation; never create a folder merely by opening it. Super Wrap may reuse this style only after P2-M4 adds the corresponding flow.

**Dialog type 7 — organizer confirmation:** developing source uses one `QMessageBox.question` pattern for Delete and accepted external-cut batches, currently Ok/Cancel and at most 15 preview lines. Preserve its accept/cancel branch but give the acceptance a descriptive label: “Move to Recycle Bin” for Delete, “Move here” for cut. Use 560 preferred/max 640 width, 24 padding, title 16/600, body 14/20, 16 gaps, 40-high buttons, and a bounded scrollable full scope list. Header includes operation/count; cut shows captured destination and any already-completed/skipped count. Delete uses status.error, cut status.warning; Cancel initially focused. Hover/pressed/focus/disabled follow §9, no empty/loading selection state in confirmation itself. Cancel/close changes nothing and returns to Organize. After acceptance the actual worker controls busy feedback. Clamp/scroll at small screen sizes; never hide affected scope behind an inaccessible “and more”. Keep toolbar label Delete. No permanent-delete fallback or new Undo promise. Successful Copy confirms clipboard references were copied, not that destination files exist.

Partial outcomes render completed/failed/unattempted groups with each source/destination; `copied_source_kept` explicitly says the destination copy exists and the source remains. Offer retry only when executor exposes a valid resumable request; do not create retry state in the view. Preserve identity/acknowledgment rules in the Phase 2 contract. Full-plan collision errors identify paths before mutation; no automatic merge. Keep grouping algorithms unchanged. Dialogs and outcome details cap height and scroll; main mode/browser navigation follows functional path-lock rules.

Future integration points: `src/late_night_workshop/ui.py` (`organize`, `OrganizeWorker`, `organize_finished`, `describe_outcomes`), `organizing.py`, `workshops.py`; proposed `src/late_night_workshop/super_wrap.py`. Backend files are dependencies, not visual-redesign edit targets.

### 8.10 Conditional Phase 2 surface B — Recent downloads

**Status:** provider exists; tray/filter/import UI pending P2-M6. Use the existing recent-downloads.svg; no new “bin” art is needed. Bottom-left button reads **Recent downloads**, has a 24 icon, 40 minimum height, and survives mode changes. A tray is a reference list, not a second downloads folder or Recycle Bin.

Use a parented app-owned dialog, preferred 640 × 480 DIP, maximum 80% of available screen. Hierarchy: title → “Completed Chrome downloads from the last hour” → Refresh → scrollable list → captured/current workshop destination → Copy to current folder / Close. Each 64-minimum row shows selectable filename, source path and completion time; body 14, metadata 12/13. Use localized local time with time zone in tooltip/full description; distinguish completion time from file modification time. Relative “minutes ago” need only update on the contract's refresh/reconciliation triggers. No live timer.

Hover/checked/focus use shared row states; no selection disables copy with visible reason. Discovery in progress shows loading only while actual provider work runs. Empty: empty-downloads.svg 144 square, “No recent downloads”, provider/window scope beneath. Provider error is an error notice, not a false empty success. Expired/missing entries disappear on reconciliation without deleting files. Copy action shows actual outcomes/collision-adjusted names and keeps originals. Do not broaden support beyond verified Chrome profiles, substitute timestamps, or scan the whole machine. Escape/Close closes this view without implying an active import was cancelled. Prevent closing from losing an active operation's feedback according to the completed functional UI contract.

Future files: `src/late_night_workshop/ui.py`, existing `downloads.py`, `organizing.py` executor, packaging asset mapping. No new downloads-navigation page.

### 8.11 Conditional Phase 2 surface C — Name tags

**Status:** documented, pending P2-M5; embedded under Recent downloads at the browser's bottom-left, not a separate page. Hierarchy: Name tags heading 14/600 → folder scope caption 12 → text input and + target → up to six wrapping chips → short helper/error. Use primary surface, 12 gaps; input 40, + button 40 square; chips 36 minimum, 8 gaps. Keep tag names exact; lengthy labels elide in chips with full tooltip/name.

Each chip shows name-tag.svg or drag-grip.svg (not both when space is tight), label, and independent remove target. Hover gives grip visibility/emphasis and a drag cursor; keyboard focus stays visible. At six tags disable creation with “Six tags per folder. Remove a tag to add another.” Invalid/duplicate names show existing validation below input. Drop on eligible ordinary file gets focus-color outline + target highlight; invalid folder/empty-space drop does not suggest success. In progress/failed rename reflects actual outcomes; counters never advance just for visual success. Removing a chip never deletes files or resets its counter history.

Current folder supplies scope and existing backend counters. No global tags, automatic external folder tracking, or redesigned persistence. Tags wrap to available width; their region may scroll at short height while keeping the add field visible. No large illustration. Keyboard equivalent for a tag's existing one-file rename command is Required for accessibility once that command exists: select one eligible target and activate “Apply tag to focused file” from the tag control's accessible menu, invoking the same backend request; do not create a second rename algorithm. If that UI command is not yet authorized in functional scope, record the accessibility gap and defer chip drag UI acceptance rather than claiming a keyboard-complete flow.

Future files: `src/late_night_workshop/ui.py`; proposed `src/late_night_workshop/name_tags.py` and existing workshop/organizer owners. No counter mutation in presentation handlers.

## 9. Reusable Component Specifications

All components inherit type/spacing from §§5–6 and states from §4. **Default state contract:** normal → hover → pressed is visual only; activation uses existing callbacks. Focus is persistent while keyboard-focused, independent of hover. Disabled blocks activation and keeps a visible reason where needed. Do not style disabled by reducing the opacity of an entire panel. Loading retains label/width, adds a loading glyph when actual work is running, and disables duplicate activation. Selected/check state is independent of list cursor focus.

| Component / dimensions | Default | Hover / pressed | Focus / disabled | Additional state / implementation notes |
|---|---|---|---|---|
| Primary button, 40 high, icon 20/24 + gap 8 | action.primary, text.primary, radius 8, 1 control edge | primary.hover / primary.pressed | 2 focus ring / state.disabled + text.disabled | Used for Open Workshop, Generate, explicit dialog acceptance; one dominant action per context |
| Secondary button, 40 high | surface.primary, control border, primary text | state.hover / state.pressed | shared focus / disabled | Create, Back, output access, clipboard commands |
| Destructive button, 40/44 high | surface.primary, status.error text/edge | status.error.bg / error.pressed | focus ring retained / disabled palette | Recycle confirmation and recent removal; text explains scope; no red icon alone |
| Icon button, 36 square (remove 32) | transparent on parent, primary glyph | hover / pressed background | shared ring / disabled glyph | Accessible name mandatory; tooltip after 500 ms; no unlabeled destructive × |
| Mode/navigation item, 40/44 high | secondary text on parent | hover / pressed | ring / disabled | selected background + 3 marker + checked semantic state; no fabricated navigation routes |
| File/folder row, 44 minimum | primary text on primary surface | hover / pressed | outline on focused row; unsupported entries disabled for generation only | Checked canonical selection: selected fill + check; after P2-M2 separate folder navigation from selection |
| Selected input/recent row, 56 minimum | basename 14 + relative/parent path 13 | same row states | same focus; per-remove focus if available | No general “selected” fill for whole Selected Inputs list; each entry is already an input |
| Card/panel, radius 12/padding 16 | primary surface/subtle border | static unless itself an action | no tab stop for decorative container | Loading/empty/error content changes inside stable frame; never blanket hover on static cards |
| Dialog, radius 12/app-owned | elevated surface, 24 padding | only child controls react | focus trapped in modal; native close supported as defined | Title 16/600, body 14, supporting 13; safe initial focus; bounded scrolling |
| Text/spin/select input, 40 minimum | secondary surface, control edge, primary content | edge focus color on hover; pressed is normal active control | 2 focus edge; disabled palette | Invalid edge error + text below, focus perimeter still visible; selection uses selected fill; placeholder muted |
| Combo popup | elevated surface, rows 36 minimum, primary text | hover/pressed states | focused item indicated; disabled items labelled | selected item uses selected fill/check; standard keyboard navigation; icon 20 per task |
| Checkbox, 20 glyph in ≥32 target | primary surface, control edge | hover/pressed frame | focus ring / disabled palette | checked selected fill + light check, no color-only selection; label clickable; use native accessible role |
| Tooltip | elevated, control border, radius 8, 8 padding | no interactive hover/press | does not steal focus | 12/16 text; max width 320; wrap; disabled reason also available without tooltip |
| Notice/error panel | semantic background, icon 20, message, details | static | text selectable; no fake disabled state | Label Success/Failed/Warning/Information + symbol, never just color; keep consequential errors persistent |
| Progress, 4–6 high | track + fill | no hover/press | accessible stage text, no interactive tab stop | busy range until genuine measurable progress exists; loading.svg 20; no fabricated percentage |
| Badge/status label | semantic text on semantic background, 4 × 8 inset | static | accessible text, no tab stop | 12/600; no required meaning conveyed by tiny badge alone |
| Empty panel | centered icon/art + heading + short instruction | existing action reacts | normal action focus | Illustration 120–160 square; not a clickable placeholder row |
| Scrollable details/list | primary/inset surface; scrollbar §6 | scrollbar hover/press | keyboard scrolling and visible focus | Preserve message text; path elision only for list summaries, not the sole error explanation |

Use existing native buttons, checkboxes, combos and spin boxes. A styled `QFrame` plus standard labels/buttons is enough for most cards/notices. Avoid one custom widget class per token. Keep Qt item views for large lists; a small delegate may render check/path states without installing a full widget per row. If row buttons are used for Selected Inputs, ensure accessible naming and bounded list cost.

## 10. Icon and Illustration Integration Map

All 29 UI icons were inspected: 24 × 24 viewBox, self-contained transparent SVG, light `#DCE9FA` stroke/fill, 1.8 stroke, round caps/joins. All three illustrations are editable SVGs; welcome is 600 × 400 with its own navy background, while both square 240 × 240 spots are transparent apart from artwork/shadow. Do not promise a transparent welcome illustration.

Full asset paths are repository-relative below. Phase 2 icon assignments are not evidence that their controls have passed functional acceptance; downloads/tags are still conditional. Keep text labels for Wrap, Rip, Super Wrap and Recent downloads; their small silhouettes supplement names. Do not use study-output icons to identify arbitrary source PDFs whose role is unknown.

| Screen / Component | Action | Existing Icon | Recommended Size | Notes |
|---|---|---|---|---|
| Organize | Wrap | `icons/ui/wrap.svg` | 24 | Two sheets enter one folder; move, not copy |
| Organize | Rip | `icons/ui/rip.svg` | 24 | Intact sheet/up arrow; exact helper visible |
| Organize | Super Wrap | `icons/ui/super-wrap.svg` | 24 | Nested/branching collection; grouping stays deterministic |
| Workshop footer / tray | Recent downloads | `icons/ui/recent-downloads.svg` | 24 | Shallow tray + arrow + clock; never Delete |
| Organize / delete confirmation | Delete | `icons/ui/delete.svg` | 24 | Wastebasket; destructive treatment provided by container/text |
| Organize | Copy | `icons/ui/copy.svg` | 24 | Clipboard references; not output duplication |
| Organize | Paste | `icons/ui/paste.svg` | 24 | File-list clipboard action |
| Downloads | Copy to current folder | `icons/ui/copy-to-folder.svg` | 24 | Single source entering destination folder |
| Mode selector | Organize | `icons/ui/organize.svg` | 20 | Folder/dividers |
| Mode selector | Make me | `icons/ui/make-me.svg` | 20 | Document/sparkle |
| Generation form | Generate | `icons/ui/generate.svg` | 24 | Primary action; no decorative repeated sparkles |
| Browser/recents/output-folder button | Open folder | `icons/ui/folder.svg` | 20 | Replaces literal `[folder]` |
| Browser toolbar | Up | `icons/ui/up-one-level.svg` | 20 | Parent navigation, disabled at root |
| Toolbar/tray | Refresh | `icons/ui/refresh.svg` | 20 | Only when corresponding behavior exists |
| Selected Inputs | Deselect | `icons/ui/remove-selection.svg` | 16 | 32 target; × never deletes a file |
| Name tags | Tag | `icons/ui/name-tag.svg` | 20 | Use on chip or section; avoid visual repetition |
| Name tags | Add tag | `icons/ui/add.svg` | 20 | 40 target; accessible Add tag |
| Name tags | Drag handle | `icons/ui/drag-grip.svg` | 16 | Redundant cue; keyboard equivalent required |
| Generation/provider | Busy | `icons/ui/loading.svg` | 20 | Static arc may rotate at runtime; stop when idle |
| Progress/result | Success | `icons/ui/success.svg` | 20 | Accompany explicit success text |
| Errors/decisions | Warning or failed notice | `icons/ui/warning.svg` | 20/24 | Error label/color distinguishes failure; no need to invent an error glyph |
| Task chooser / generated notes label | Notes | `icons/ui/notes.svg` | 20 | Open notebook/pencil |
| Task chooser / generated summary label | Summary | `icons/ui/summary.svg` | 20 | Page/short lines |
| Task chooser / generated cheat-sheet label | One-page cheat sheet | `icons/ui/cheat-sheet.svg` | 20 | Two-column reference |
| Task chooser / output label | Sample questions | `icons/ui/sample-questions.svg` | 20 | Question page |
| Task chooser / output label | Answer key | `icons/ui/answer-key.svg` | 20 | Checked page |
| Task chooser / output label | Checklist | `icons/ui/checklist.svg` | 20 | Checkbox rows; not selection control artwork |
| Task chooser / output label | Make schedule | `icons/ui/schedule.svg` | 20 | Calendar grid |
| Task chooser / output label | Make daily study plan | `icons/ui/daily-study-plan.svg` | 20 | Single-day checklist |
| Start page | Welcome artwork | `icons/illustrations/welcome-desk.svg` | 300 × 200 | Max 360 × 240; hide before content becomes cramped |
| Empty browser | Empty workshop | `icons/illustrations/empty-workshop.svg` | 144 × 144 | Open folder and loose sheets; no in-art text |
| Empty tray | Empty downloads | `icons/illustrations/empty-downloads.svg` | 144 × 144 | Crescent moon/shallow tray; keep scoped helper below |

No new icons generated. For generic source documents and Back, use a standard Qt/platform icon or text. Do not repurpose summary.svg for every file or rip.svg for parent navigation. Tooltips/accessibility labels live on controls; SVG `<title>` alone is insufficient.

**Future asset wiring:** `icons/` currently sits outside the import package and is not included by the current package-data list. During UI-M7 choose one explicit bundled mapping: include `icons/ui/` and `icons/illustrations/` under the package's runtime asset directory in both setuptools package data and PyInstaller `datas`. Retain originals and filenames. Use a single resource lookup near `resource_path()`; do not load relative to current working directory. Verify source and packaged lookup separately. This task does not make those packaging changes.

QSS foreground color does not automatically recolor these fixed-color SVG paths. Keep originals intact; if a semantic-colored glyph is needed, render and tint a runtime pixmap using a mask/composition operation and a named token, cache by path/size/device pixel ratio/state. Required alternative: keep light glyphs, use semantic container/text, and avoid a tint subsystem. Dark text/light primary buttons were deliberately avoided so originals remain legible.

## 11. Microinteractions and UI Feedback

| Interaction | Required final state | Optional motion |
|---|---|---|
| Button/row hover | New background; no size shift | 100–120 ms, ease-out |
| Press | Pressed token immediately | No scaling, bouncing or delayed activation |
| Selection/mode change | Check/marker and text/count update synchronously | Color fade 100 ms; no sliding panel |
| Busy spinner | Only while actual work pending | 900 ms linear revolution; stop when hidden or waiting |
| Progress | Honest busy stage/message | Native indeterminate movement, no fake completion |
| Success | Persistent result card until next existing state transition | Single 120 ms opacity appearance; no confetti |
| Error | Persistent message and next step | No motion; no auto-dismiss |
| Dialog | Immediate focus transfer and safe initial button | Native appearance; optional 100 ms fade only if reliable |
| Optional detail expansion | Expanded content and clear disclosure label | 120 ms ease-out, avoid frame jumps |
| Tooltip | Text after 500 ms hover; available on focus where useful | No custom animation needed |

Qt Widgets QSS is not browser CSS: do not use CSS transitions, transforms, grid, box-shadow or line-height. Static state styling is Required; animations are Optional. If necessary use a small `QPropertyAnimation` on an actual supported widget property, not a general animation framework. Do not animate a timer per list row. Spinner updates must stop on completion and must never initiate jobs/download refresh.

Honor the platform reduced-motion/animation preference when it is available through the deployed Qt/Windows environment. If detection is unreliable, ship static state changes by default and limit busy feedback to text/native progress. A static arc plus “Generating…” is acceptable with motion reduced; never remove the stage text. No new in-app animation-settings page is required.

## 12. Window Resizing and Accessibility

### Resize contract

- **Required baseline:** initial client size 1200 × 780 DIP when available; practical minimum 960 × 640 DIP. Clamp initial geometry to active screen available area. On a screen smaller than that minimum, permit an 800 × 560 fallback with scrollable form/details rather than forcing content off-screen. Treat minimums as practical layout targets, not a refusal to fit the user's display.
- At ≥1100 width: 24 page padding, browser flexible ≥440, right panel default 376. At 960–1099: 16 padding, 16 gap, right panel 336–360, hide welcome art. Below 960 available width: browser may shrink to 320 and right panel to 320; selected list height 120, helpers wrap, action buttons stack where needed. No collapsed icon-only mode that hides essential labels.
- Short height: reduce decorative/empty art to 96–120, cap results details, scroll the form. Generate/destination remains reachable in a visible footer. Do not shrink text or targets to force a fit. The browser retains its own scroll area; avoid nesting it inside whole-window scrolling unless the fallback truly requires it.
- Root path: middle-elide while retaining drive and workshop name. List filename: right-elide stem while preserving extension when feasible; duplicate basenames show relative parent path. Current relative folder and selected paths: middle-elide the parent sequence, retain last segment. Tooltip/accessibility description contains full value. Error/log/details areas wrap without losing essential path content and support text selection/copy.
- Large file lists: keep Qt item-view scrolling; no new filtering/search/infinite-loading feature. Preserve scroll/focus where the existing refresh contract allows it; do not claim improved filesystem performance. Do not instantiate heavy hover animations/widgets for every row. Header/footer must not grow with the list.
- Modal dialogs parent to main window, remain in the available geometry of its screen, and cap scrollable body at 60% of available height. Native dialogs follow platform behavior. Never center against the combined virtual desktop when it places content between monitors.
- Qt uses device-independent widget coordinates; SVG and runtime rasterization must honor device pixel ratio. Verify at 100%, 125%, 150%, 200%, and while moving between unlike-DPI monitors; no manual global multiplication of widget sizes. Font enlargement may exceed nominal line heights. See [Qt High DPI](https://doc.qt.io/qt-6/highdpi.html).

### Keyboard, semantics and contrast

**Required:** tab order follows visual order: Workshops → Up → Refresh if present → browser → Selected Inputs/removal → mode if present → Output type → Task → visible parameters → Efficient → Generate → result actions. Download/tag controls follow their visible browser order without unexpectedly interrupting a form traversal. Hidden controls are not tab stops. Standard combo/spin/input keys work; Enter/Space activates focused buttons. In a file list, arrow keys move focus, Space toggles the canonical selection through the existing selection owner, Enter opens a folder or invokes the same supported-file selection action as the click handler. Verify a keypress invokes it once. Escape only closes/cancels contexts that already support it; it is not a new generation-cancellation shortcut.

Recommended presentation shortcuts: Alt+Up for existing Up; F5 for existing Refresh. Avoid global Delete/Ctrl+V shortcuts until the functional organizer's selection/clipboard integration is accepted; shortcuts must not fire while typing a name. Every pointer action must have an equivalent supported keyboard route, including Phase 2 tag application as discussed in §8.11.

Use standard Qt accessible controls; set accessible names/descriptions for icon-only controls, row removal, stage messages and path values. Labels identify/buddy the corresponding inputs. Check state, disabled state and focused state must reach assistive technology, not just paint. Use meaningful selected/current semantics rather than describing every blue row as “selected” when it is only focused. Decorative art has no keyboard focus or repeated spoken description. Qt exposes standard widget metadata to platform assistive tools; custom-painted row actions need explicit accessible behavior. Verify with Windows Narrator/UI Automation rather than assuming visual labels suffice. See [Qt Accessibility](https://doc.qt.io/qt-6/accessible.html).

Announce stage changes, blocking decisions and final outcomes using the deployed Qt accessibility event route where supported. Do not announce every spinner frame. Avoid stealing focus from a typing user for nonblocking success feedback; preserve existing first-PDF auto-open. Keep errors selectable and next steps actionable without exposing keys. Disabled-state explanations must be visible or keyboard-readable, not hover-only.

Normal enabled text ≥4.5:1; essential boundaries, checkmarks and focus ≥3:1 against adjacent colors. Status always includes words and a glyph; selected entries include a check. Minimum dense target 32 square; common action 40 high; larger rows 44/56. Use system high-contrast colors if requested by the OS; preserve recognizable roles without forcing the navy aesthetic. Reduced-motion policy is in §11.

# Post-Implementation UI Redesign Roadmap

## 13. Roadmap Scope and Milestones

Begin after functional milestones land. Before each UI milestone, re-read current `architecture.md`, `components.md` and `workflow.md`; Claude is implementing concurrently and this snapshot can become stale. These milestones alter presentation only. Existing functional helpers, event/result structures, data models, safety rules and algorithms remain authoritative. If a dependency is absent, defer that surface rather than implementing its backend in a UI milestone.

### UI-M1: Design Tokens and Global Theme

- **Objective:** establish the shared visual system without moving workflows.
- **Components/files:** application setup, standard controls, labels, lists; existing `src/late_night_workshop/ui.py`; proposed `src/late_night_workshop/theme.py` only if shared styling merits a separate cohesive module.
- **Changes/deliverables:** semantic token mapping, QPalette/QSS, named font/spacing constants, primary/secondary/destructive roles, status and input states; one consistent default shell.
- **Dependencies:** completed functional baseline; §§4–6 and §9.
- **Acceptance:** existing two pages readable; every normal/hover/focus/disabled/selected role implemented; verify contrast including status backgrounds, controls against every adjacent surface, and high-contrast override; no isolated `#666666`/`#888888` overrides remain in UI presentation.
- **Non-goals:** new screen, theme selector, font dependency, business-logic changes, animation system.

### UI-M2: Application Shell and Navigation

- **Objective:** adapt both pages to desktop resizing and clarify workshop location.
- **Components/files:** `Window.__init__`, `_start_page`, `_workshop_page`, header, root/current labels, Up/Back; `src/late_night_workshop/ui.py` plus shared styling.
- **Changes/deliverables:** 56-high header, two-column splitter, 376-default right panel, path elision, bounded scroll areas, initial/minimum/fallback geometry; preserve OS title bar.
- **Dependencies:** UI-M1; existing navigation routes. Any Phase 2 mode selector waits for P2-M2.
- **Acceptance:** inspect 1200 × 780, 960 × 640 and constrained 800 × 560; Back and Up perform unchanged actions; current folder/root remain distinguishable; long paths do not force horizontal overflow; primary action reachable with enlarged fonts.
- **Non-goals:** global navigation architecture, routing rewrite, custom title bar, new sidebar destinations.

### UI-M3: Core Workflow Screens

- **Objective:** polish file/selection/task presentation and completed organizer controls.
- **Components/files:** `_start_page`, `refresh`, `refresh_selected`, browser/recent lists, task form, conditional Organize grid; `src/late_night_workshop/ui.py`. Read `workshops.py`, `tasks.py`, `organizing.py` contracts without altering them.
- **Changes/deliverables:** recent row hierarchy, empty panels, clear selection/focus, keyboard activation via existing callbacks, Save to cue, uniform form, conditional mode/control layouts.
- **Dependencies:** UI-M2; P2-M2 for selection removal/Refresh/modes; P2-M3/P2-M4 for actual organizer commands. Existing generation form can be completed independently.
- **Acceptance:** select across folders, navigate to destination, choose Summary then a study plan, and verify identical request values; keyboard action toggles only once; removing an available Phase 2 blocker preserves other inputs/parameters; all six organizer labels/eligibility reasons are correct when integrated.
- **Non-goals:** new organizer executor, selection ownership changes, task defaults/range changes, grouping algorithm changes, drag sorting.

### UI-M4: Generation and Progress Experience

- **Objective:** make running/waiting/failure/success understandable and stable.
- **Components/files:** `generate`, `describe_progress`, `choose_for`, `answer_decisions`, `job_finished`, status presentation in `src/late_night_workshop/ui.py`; read `generation.py` event/result contract.
- **Changes/deliverables:** bounded feedback card, stage label, indeterminate progress, captured destination, field-associated existing errors, selectable diagnostics; scan decision layout.
- **Dependencies:** UI-M1/UI-M2; UI-M3 form. Use existing Worker string messages; no event-schema rewrite for a progress bar.
- **Acceptance:** present fixture states for every row of §8.3; one scan decision preserves Process original/Cancel mapping and worker handoff; long render/error messages scroll; no ETA/fake percentage/general Cancel appears; no UI handler duplicates an API call.
- **Non-goals:** retries, cancellation pipeline, altered transmission consent, API/model changes, timing telemetry system.

### UI-M5: Output and Study Material Experience

- **Objective:** make returned outputs easy to find without building a document manager.
- **Components/files:** `job_finished`, `open_document`, `open_output_folder`, output buttons and conditional downloads tray in `src/late_night_workshop/ui.py`; existing `downloads.py` and publisher contracts are read-only dependencies.
- **Changes/deliverables:** success count/root/details, task-appropriate result labels, bounded daily-path list, warnings hierarchy; tray row/empty/provider-error/import feedback styling if P2-M6 is complete.
- **Dependencies:** UI-M4; P2-M6 for tray. UI-M7 may supply final asset wiring, with text/native icon placeholders until then.
- **Acceptance:** single output and a two-day six-output fixture show actual returned paths; Open document still targets first result and auto-open remains; output folder uses returned root; long output list never pushes controls off-screen. If tray is present, one import shows original retained and actual destination, with provider failure distinct from empty.
- **Non-goals:** PDF embedding, result history/database, output renaming, browser support expansion, timestamp filtering changes.

### UI-M6: Dialogs and Secondary Components

- **Objective:** align app-owned dialogs, helpers, name tags and feedback semantics.
- **Components/files:** `ask_name`, `open_recent`, `create_workshop_dialog`, `choose_for` and conditional action/tag dialogs in `src/late_night_workshop/ui.py`; shared theme; proposed `name_tags.py` only as a completed backend dependency.
- **Changes/deliverables:** seven source-visible dialog types per §8.4–§8.9, with the two organizer types gated by accepted P2-M3; standard spacing/buttons/safe focus; tag chip/drop target styles and truthful partial-outcome notices after Phase 2.
- **Dependencies:** UI-M1/UI-M3/UI-M4; P2-M5 for tags; completed organizer outcomes for partial feedback.
- **Acceptance:** folder chooser stays native; cancel every existing dialog without unintended side effects; missing recent removal means recent entry only; long source/page lists fit; Delete confirmation uses actual scope; partial moves never display generation's “Nothing was saved” guarantee; no settings page added.
- **Non-goals:** credentials editor, new validation rules, clipboard/recycling adapter work, counter persistence implementation.

### UI-M7: Icons, Illustrations and Microinteractions

- **Objective:** finish asset integration and restrained feedback.
- **Components/files:** `src/late_night_workshop/ui.py`, resource lookup near `src/late_night_workshop/__init__.py`, shared theme; future package-data/resource declarations in `pyproject.toml`, `packaging/late-night-workshop.spec`, and release staging only if required. Existing `icons/` originals are read-only inputs.
- **Changes/deliverables:** packaged local SVG mapping for §10; accessible labelled icons; welcome/empty illustrations; Optional minimal transitions, Required static reduced-motion behavior.
- **Dependencies:** UI-M1–UI-M6 controls available; text-first screens need not wait for this milestone. Organizer/download asset wiring only for accepted functional surfaces.
- **Acceptance:** all used icons load from source and frozen build launched outside checkout; priority glyphs read at 24 DIP; 125–200% scaling stays sharp; no light SVG placed on an unreadable light button; no animation after idle/hidden, no runtime network asset fetches.
- **Non-goals:** replacement icon library, new artwork campaign, editing existing SVG originals, installer branding, decorative animation framework.

### UI-M8: Final Visual Consistency and Accessibility Review

- **Objective:** verify the implemented presentation against this specification.
- **Components/files:** all delivered UI surfaces, theme/resources and package declarations; UI fixes only in their owning presentation files.
- **Changes/deliverables:** focused fixes plus a concise review record of inspected sizes/states, contrast and keyboard/screen-reader outcomes.
- **Dependencies:** UI-M1–UI-M7 for their accepted scopes; completed functional Phase 2 before claiming Phase 2 accessibility/visual acceptance.
- **Acceptance:** §15 checklist passes; inspect two main pages, seven dialog types when P2-M3 is accepted, both existing modes, generation states and accepted downloads/tag surfaces; one representative generation boundary smoke check reuses existing fixtures; one packaged lookup check; no accidental changes to request/output contracts.
- **Non-goals:** full-suite run by default, benchmark, backend refactor, new CI, all-task paid API rehearsal.

## 14. Claude Implementation Guidelines

1. **Required — re-establish reality.** Read current implementation first. This document does not mark functional milestones complete. `components.md` records P2-M2 and P2-M1's planner/provider, while concurrent source is actively advancing P2-M3 execution. Preserve teammate edits and use the commit agreement in `AGENTS.md` when implementation occurs.
2. **Required — introduce shared styling simply.** Start with a small token mapping, font/spacing constants and one stylesheet/palette application in `run_app()`. A single `theme.py` is enough if separating presentation setup clarifies responsibility; no plugin framework, generated token build, third-party theme package or web frontend. Leave `Window`/`Worker` local unless a separately justified functional change requires extraction.
3. **Required — name component roles.** Set a small set of object names/dynamic properties such as `role=primary`, `role=destructive`, `state=error` on app-owned controls. Use QSS selectors for `:hover`, `:pressed`, `:focus`, `:disabled`, `:checked`, and appropriate item-view subcontrols. Re-polish a widget when a dynamic style property changes. Test focus separately from model selection. Qt supports widget-specific stylesheet properties/subcontrols; consult the [Qt Style Sheets Reference](https://doc.qt.io/qtforpython-6/overviews/qtwidgets-stylesheet-reference.html), not browser CSS documentation.
4. **Required — preserve boundaries.** UI renders/captures/delegates. Workshop helpers own canonical selection/path truth; tasks own parameters; Worker/generation own the job; organizer owns plans/outcomes; tags own counters; downloads owns discovery/filtering. Do not infer completion from a painted green row, mutate filesystem paths from a delegate, or implement a second selection set in the view.
5. **Required — retain contracts.** `build_request` keeps workshop root/current destination/selected paths/task/parameters/Efficient. Defaults and supported MIME/extension rules remain. No API calls or persistent-data writes while merely opening a design preview. No new progress schema, retries, cancellation, OCR, math rendering or overwrite behavior for visual convenience.
6. **Required — respect threads.** Standard widgets/dialogs and UI-bound clipboard work remain on UI thread; filesystem/generation work follows existing worker boundaries. Preserve `quit()` before `wait()` and the scan decision Event signaling. Never block the GUI just to animate progress or generate previews.
7. **Required — keep feedback honest.** Generation's all-or-nothing guarantee is not an organizer transaction guarantee. Present partial outcomes from records; don't synthesize safe retry state. Rendering warnings/errors as plain text avoids markup interpretation. Only show available controls backed by accepted functional helpers.
8. **Recommended — map components incrementally.** Apply global controls first, then layout, lists/form, progress/results, dialogs, resources. Reuse standard Qt widgets; use a lightweight delegate only for genuine list-row needs. Keep shared styles in one place and screen composition in existing UI methods. Do not add a large generic component layer.
9. **Required — asset paths.** Resolve bundled resources independent of launch directory; preserve source originals. Any future packaging edits belong to UI-M7, not this planning task. Retain `icons/preview.html` as a read-only asset reference.
10. **Required — focused verification.** Reuse existing test seams/fixtures; one meaningful interaction or changed boundary check per milestone plus representative visual states is sufficient. No broad tests for token constants or mirrors of QSS. Do not make live Gemini calls merely to inspect progress states; use fixtures/existing injected dependencies. Run broader checks only for a demonstrated cross-cutting risk or explicit request.

| Existing UI owner | Design responsibility | Contract to preserve |
|---|---|---|
| `Window._start_page`, `show_start` | Welcome/recents/empty hierarchy | Recents persistence/open/remove routes |
| `_workshop_page`, `refresh`, `refresh_selected` | Shell, file rows, selected inputs, disabled reasons | Canonical selection, root/current paths, generated-button eligibility |
| `output_type_changed`, `task_changed`, `current_parameters` | Conditional form styling | Exact registry task IDs, styles, defaults and validation |
| `generate`, `Worker` | Action/busy presentation | Snapshot and threaded generation/decisions |
| `choose_for`, `answer_decisions` | Scan dialog design | Process original vs Cancel; UI-thread handoff |
| `job_finished`, `describe_error`, `describe_progress` | Outcome/stage/error hierarchy | Actual stage/message/path/warning and error guarantees |
| `open_document`, `open_output_folder` | Result action styling | First-document opening and returned output root |
| `organize`, `OrganizeWorker`, `organize_finished`, `describe_outcomes`; future tray/tag callbacks | Organize/downloads/tags presentation | Accepted owners' eligibility, snapshots and partial outcomes |

## 15. Final UI Acceptance Checklist

This is a checklist for the future implementation, not a claim that the redesign has shipped.

- [ ] Two existing main screens and seven source-visible dialog types follow §§7–8 after P2-M3 acceptance; no invented settings/result-library destinations.
- [ ] Organize/Make me preserve existing P2-M2 behavior; organizer execution acceptance is rechecked, and Recent downloads/Name tags appear only after their owners pass.
- [ ] Color, font, spacing, radius and control-state tokens are shared; no arbitrary per-handler theme colors; native OS dialogs remain usable.
- [ ] Enabled body text meets 4.5:1; controls/focus meet 3:1; disabled controls retain readable explanations; all status meanings have words/glyphs.
- [ ] Primary actions dominate once per context; Delete, recent removal and deselection are visibly/semantically distinct.
- [ ] Every interactive control has default/hover/pressed/focus/disabled styling; selection is independent of cursor focus; loading is actual work only.
- [ ] All eight tasks retain parameter/default/output behavior; Efficient off/note and scan consent semantics remain intact.
- [ ] Destination is explicit; a running job shows the captured destination even when the user browses elsewhere.
- [ ] Progress uses real stages/messages with no unsupported percentage/ETA; cancellation is offered only where supported.
- [ ] Success uses returned paths, preserves first-PDF auto-open, and keeps output buttons accessible with large daily plans.
- [ ] Errors retain recovery guidance/log location; long paths/messages scroll or wrap; partial organizer outcomes never promise nothing changed.
- [ ] Existing icons map consistently through §10; no duplicate assets; artwork is limited to welcome/empty states and preserves aspect ratio.
- [ ] Priority icons read at 24 DIP; packaged/source assets load outside the checkout/current working directory.
- [ ] Initial, minimum and small-screen fallback layouts work; long/duplicate filenames, empty lists and many results remain readable.
- [ ] 100%, 125%, 150%, 200% scaling, enlarged fonts and mixed-DPI movement preserve targets and text.
- [ ] Tab/arrow/Space/Enter/Escape behavior is verified; icon controls have accessible names; Narrator announces decisions/outcomes without animation spam.
- [ ] Reduced-motion/high-contrast preferences are respected; no decorative motion is needed to understand status.
- [ ] Conditional tray scope remains verified Chrome/last-hour/on-demand; originals are retained on import; no discovery timer is introduced.
- [ ] Conditional chips respect folder scope/six-tag limit/counter outcomes and offer an accessible equivalent to their rename gesture.
- [ ] Eight milestones have reviewable presentation deliverables; no redesign milestone changes processing algorithms, APIs, data models or filesystem behavior.

### Planning-task verification record

The design was checked against the two-page Qt source, five established dialog types plus two organizer dialog types appearing during concurrent development, eight-task registry contracts documented in the component map, all 29 UI SVGs, three illustration SVGs and their contact sheet. The final source refresh found P2-M2 implemented and P2-M3 actively developing; it did not establish runtime acceptance of organizer execution. Token contrast examples were calculated locally with the sRGB relative-luminance formula. Source and asset inspection was read-only; no application, automated formatter, package installation, build, API request or test suite was run. Qt documentation was consulted for stylesheet scope, high-DPI coordinates and accessibility support; recommendations still require verification against the deployed PySide6 version.

Only `design.md` is created by this planning task. No new icon is needed, and all existing assets remain unchanged. The initial working tree already contained concurrent changes to architecture/components/workflow, Phase 2 planning/source/tests and the untracked `icons/` collection. Source and documentation hashes changed during this task as Claude continued work; none of those writes were performed by this task. Do not stage, revert or claim those edits with the design document. The asset hashes remained unchanged at the final comparison.
