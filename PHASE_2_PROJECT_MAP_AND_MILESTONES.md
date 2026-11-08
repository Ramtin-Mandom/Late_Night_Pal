# Late Night Pal — Phase 2: file organization map and milestones

## Purpose and status

Phase 2 adds local file organization to the existing desktop workshop. This is an implementation plan; none of the features below are implemented by this document. This documentation revision changes this file only. Existing source, architecture, workflow, README, and Phase 1 milestone files remain untouched.

The verified baseline in `architecture.md` is implemented through Phase 1 M7: a Python/PySide6 desktop app, real workshop folders, a browser, cross-folder file selection, and eight generation tasks. `ui.py` owns the workshop screen; `workshops.py` owns browsing, selection, containment, and recent workshops. Folder clicks currently navigate, and only the five generation-supported file formats are selectable in the UI. Phase 2 must extend those behaviors deliberately.

This plan supersedes the Phase 1 exclusion of manual file organization for Phase 2 only. Make me keeps its existing generation behavior, parameters, supported inputs, progress, and output layouts. Organization runs locally without Gemini, text extraction, or LaTeX.

The hackathon download target is completed downloads recorded by one Windows demo browser. No demo browser is identified in the repo, so **Chrome is the proposed target; support is unverified until P2-M1**. Coverage includes custom save locations and downloads completed before app launch. Computer-wide discovery across browsers and other download tools is future scope. A failed browser feasibility check blocks P2-M6 and full P2-M7 handoff, while P2-M2–P2-M5 can proceed.

## Workshop layout and selection

- Immediately below **Selected Inputs**, show two visible choices: **Organize** and **Make me**. Use tabs or a two-button selector, not an action dropdown. Default to Make me for continuity; switching modes retains selection and Make me parameters.
- Make me contains the existing output type, task, parameters, Efficient option, and Generate controls.
- Organize contains six direct-action buttons: **Delete**, **Rip**, **Wrap**, **Copy**, **Paste**, and **Super Wrap**. An unavailable action is disabled with a short reason.
- Keep the button name **Rip** and show this helper text: “Move each selected folder’s contents up one level.”
- In Organize, every ordinary file type and folders can be selected. Use an explicit row selection control so clicking a folder name can still open it. Keep canonical paths and workshop-relative labels across navigation.
- Generation still accepts only its existing supported file types. If the shared selection contains folders or unsupported files, Make me names those entries and disables Generate until they are deselected; do not silently omit them.
- Beside every **Selected Inputs** entry in both modes, provide a keyboard-accessible remove control with an accessible name identifying the entry. It works even when the entry is outside the current folder view. Remove only deselects that entry; it never deletes a file. Immediately revalidate Generate, preserving every other selection and all Make me parameters.
- Place a **Refresh** button beside Up/current-folder navigation. It rescans the current folder, reconciles the shared selection, reloads that folder's tags, and updates the recent-download list if open.
- At the bottom left, beneath the folder browser, place a **Recent downloads bin** button with a custom bin icon, then the **Name tags** area. Keep both visible while switching action modes.
- Disable conflicting organization, rename, and generation actions while a job is using the affected paths. Capture the selection and destination at click time so later navigation cannot redirect a running operation.

## Action contracts

“Current folder” means the folder open in the left browser when the action is pressed. Selection may span workshop subfolders. For operations on folders, reduce a selected parent and its selected descendants to the parent once; never process the same content twice. The workshop root itself is not an actionable selection.

| Button | Inputs and behavior | Observable result |
| --- | --- | --- |
| Delete | Delete all selected files and selected folder trees using Windows Recycle Bin behavior. Show the affected selection/count before deletion; Cancel makes no changes. If recycling is unavailable, report that failure instead of falling back to permanent deletion. | Successfully deleted paths disappear from the browser and selection; failed paths remain with an explanation. |
| Rip | For each selected folder, move its immediate children into that folder's own parent, then remove the selected folder only after it is empty. Ignore selected ordinary files. This unwraps one level; child folders retain their contents. | Selecting sibling folders puts their children together in the same parent space. A folder selected elsewhere unwraps where it lives, rather than moving content into the browsed destination. |
| Wrap | Ask for a folder name. On acceptance, create a new folder under the captured current folder and move all selected entries into it. This is a cut/move operation, including entries selected in other workshop folders. Cancel creates nothing. | Originals are gone from their old locations and exist in the new named folder. |
| Copy | Place selected file/folder references on the desktop file clipboard with copy semantics. Do not copy data or remove sources at button press. | The selection can be pasted into this app or another file manager. |
| Paste | Read a file-list clipboard and copy its entries into the captured current folder; honor external cut only when the adapter can satisfy the per-item outcome, acknowledgment, and retry rules below. Validate the entire plan before changing files. Text-only clipboard content is not a file operation. | Files/folders appear in the destination with contents intact; copy sources remain, while completed cut items have their sources removed. Partial cuts are reported as partial, never as a fully completed batch. |
| Super Wrap | Ask for an outer folder name, just like Wrap. Move selected files into that new folder using the recursive grouping rules below. Selected folders move intact as opaque entries; do not recursively reorganize their pre-existing contents. | One outer folder contains grouped/renamed files, ungrouped files, and any selected folders. |

Before copying or moving anything, reject the entire plan if any folder's proposed destination is itself or lies inside it. Apply this to Wrap/Super Wrap and Paste, both copy and cut, including external clipboard entries, after resolving paths and before creating destination folders. Numbered suffixes do not bypass this containment check. A copied ordinary file may still be pasted beside itself with a numbered suffix. Rip rejects plans that would merge/overwrite existing children. Rip of an empty selected folder removes it; Rip with only files selected reports that there were no folders to unwrap.

For example, select `Lectures/a.pdf` and `Labs/b.pdf`, browse to `Coursework`, and Wrap as `Batch`. The files become `Coursework/Batch/a.pdf` and `Coursework/Batch/b.pdf`. Rip `Batch` to produce `Coursework/a.pdf` and `Coursework/b.pdf`, then remove the empty `Batch`. Rip uses the wrapper's current parent and has no original-location history; it does not restore `Lectures` or `Labs` locations.

### Naming, collisions, and stale paths

- Validate entered folder/tag names against the existing project's Windows-safe naming rules: no path separators, traversal, reserved names, invalid characters, or trailing dots/spaces. Empty/cancelled names do not start work.
- Compare planned destination names using Windows case-insensitive rules. Never overwrite or implicitly merge existing files or directories.
- For Paste, choose the next free suffix, such as `notes (2).pdf`, and report the actual name. This also lets a copied file be pasted into its own folder.
- For Wrap, Super Wrap, Rip, and tag renaming, reject a conflicting plan before changing files and identify the conflicting paths. The user can change the name or selection. Do not silently alter Super Wrap's grouping structure.
- Check containment, source existence, permissions, and destination conflicts before execution, then recheck relevant paths when executing. Reject symlinks/junctions for mutating operations rather than following them into unexpected locations.
- Ordinary organization stays within the workshop. Paste and recent-download import are explicit external-input boundaries: copy ordinary external files/folders in, but reject link escapes. External cut may remove only the explicitly supplied clipboard sources after a successful move.
- Do not promise filesystem transactions. Execute a validated ordered plan and record completed changes; on failure stop and report completed, failed, and unattempted paths. Preserve sources for failed/unattempted work wherever they still exist. For each cross-volume move, finish and verify the destination copy before removing that item's source. A destination copy whose source removal failed is not a completed move; report both paths and its exact state. Keep partially populated folders visible when necessary; remove only empty folders created by the failed operation.
- After an operation, refresh the affected view, remap selected paths for successful moves/renames, remove successful deletions, and retain unaffected selections. Reconcile clipboard references to avoid reusing stale app-owned paths.
- For an external cut batch, keep an outcome record per clipboard item tied to the clipboard request identity: source identity, reserved destination, and pending/completed/failed/unattempted state, including any copy completed before source removal failed. Stop on the first failure. Never send full-batch move acknowledgment, clear the batch as fully consumed, or trigger source-side cleanup after partial success. Acknowledge full completion only when every item is confirmed moved; any per-item acknowledgment must describe only confirmed completed items under a verified adapter contract.
- Retry only failed/unattempted items from the same recognized request; skip completed items even if a new file later occupies their old paths. Revalidate remaining source identities and destinations. Never delete a remaining source merely because a destination exists, nor blindly recopy or remove it after a partial copy/removal failure; reconcile the recorded copy and source before resuming, or stop with an explanation. Retain outcome records across app restart, or reject resumption when reliable state is unavailable. Do not reinterpret an old partial batch as a new cut when its state is uncertain.
- Before starting an external cut, verify the clipboard integration can preserve these acknowledgment/retry guarantees, including preventing source-side deletion of remaining items. If the particular request/protocol cannot safely represent partial outcomes or be reconciled for retry, reject it before changing files and explain why. Do not silently convert a rejected cut to copy.

## Super Wrap: deterministic recursive grouping

Work on filename stems; preserve each file's extension exactly. Assume underscore-separated words/numbers as supplied in the request. A numeric token consists entirely of decimal digits. Use exact token spellings for grouping; preserve capitalization and leading zeros. Treat case-only destination differences as conflicts on Windows.

At each level, compute a candidate grouping key for every remaining file stem:

1. Find its first numeric token.
2. If tokens follow that number, the key is every token through that number, inclusive. Example: `Cal_1_assignment_2` has key `Cal_1` (type 1).
3. If that number is the last token, the key is the preceding nonempty token sequence, excluding the number. Example: `assignment_2` has key `assignment` (type 2).
4. No numeric token, an empty key, or a stem without a removable underscore boundary means no candidate; leave the filename at this level.
5. Bucket by the complete key, not a truncated runtime hash. Only buckets containing at least two files produce a folder. Files alone in a bucket retain their entire current name.
6. In each qualifying bucket, create the key-named folder, remove exactly `key_` from each stem, preserve extensions, and recurse on the remaining stems inside that folder.
7. Stop when no bucket qualifies. Every recursive move removes a nonempty prefix, so recursion terminates. Never strip a prefix from an ungrouped singleton.

Build the full source-to-destination plan before moving anything. Check generated folder names, empty stems, case collisions, duplicate destinations, and file-versus-folder conflicts. Reject the whole plan if it cannot preserve every source distinctly. Existing folders supplied as selected entries are excluded from grouping and can still cause a destination conflict.

Example: choose outer folder `Coursework` and select these files:

```text
Cal_1_assignment_1.pdf
Cal_1_Note_1.pdf
Cal_1_assignment_2.pdf
```

Result:

```text
Coursework/
└── Cal_1/
    ├── assignment/
    │   ├── 1.pdf
    │   └── 2.pdf
    └── Note_1.pdf
```

`Note_1` stays intact because its `Note` bucket has only one member. `Cal_2_assignment_1.pdf` alone stays at the outer level with its full name. Two `Week_1` / `Week_2` stems group under `Week`, becoming `1` / `2`. A deeper shared stem such as `Cal_1_unit_2_exercise_1` and `Cal_1_unit_2_exercise_2` groups through `Cal_1/unit_2/exercise/{1,2}`. Files with no matching numeric pattern stay directly in the outer folder.

## Recent downloads bin

This is a recent-download tray, separate from Delete and the operating system's Recycle Bin. Generate a custom bin icon during UI implementation and bundle it as a local asset with a text label/tooltip and accessible name. This planning task does not generate assets.

- Click the bin to open a list showing filename, source location, and download time for eligible files. The requested time window is the last hour: include records where `0 <= now - downloaded_at < 3600 seconds` and the file still exists.
- Reconcile on startup, opening the tray, Refresh, and an import action. Discover new eligible records and drop expired/missing entries. No timer, background polling loop, or scheduled expiration task; an idle view may retain an entry until the next check.
- Expiring or removing a tray entry never deletes its underlying file. This tray references downloads; it is not another copy of them.
- Provide an explicit **Copy to current folder** action for selected tray entries so the bin has a complete import workflow. Use the same copy/collision rules as Paste, keep originals, and refresh the workshop afterward.
- Target completed downloads recorded by the agreed Windows demo browser: proposed **Chrome**, unverified until P2-M1. Include browser-recorded paths outside Downloads and eligible downloads completed before app launch. Computer-wide discovery across other browsers/tools is future scope. A file modification or creation time alone is insufficient evidence of download completion.
- Keep discovery behind a small provider interface returning `{path, downloaded_at, timestamp_source}`. In P2-M1, record the agreed browser/version and demo profile scope, the actual source/fields of its completion timestamp and final path, and the result of a real feasibility check with completed downloads, including a custom save location and a pre-launch download. Confirm incomplete/cancelled records are excluded. Deduplicate canonical paths and tolerate inaccessible/missing records. No probe is run as part of this documentation edit.
- If P2-M1 cannot verify that evidence for the agreed browser, record the failure and mark P2-M6 blocked. P2-M2–P2-M5 may proceed using the established operation/selection contracts. Resolve and pass browser feasibility before P2-M6 can pass; P2-M7 cannot claim full Phase 2 handoff until P2-M6 passes. Do not substitute file timestamps or a Downloads scan to pass the milestone.

## Folder-specific persistent name tags

- Beneath the bin, show a horizontal text field with a **+** button beside it. Typing `assignment` and pressing + creates a draggable chip labelled `assignment`. Keep at most six chips per folder; disable creation at six with a visible explanation.
- Reject empty/invalid names and duplicate tags in that folder using case-insensitive comparison. Provide a small remove control so users can replace a tag when all six slots are occupied.
- Each tag has its own persistent next-number counter, initially 1. Drop a chip on one ordinary file in the left browser to rename its stem to `tag_N` while preserving its extension. Dropping a chip does not move or consume the chip and does not rename the whole selection.
- Five successful drops of a new `assignment` chip produce `assignment_1`, ..., `assignment_5` in drop order. Cancelling, a failed rename, or dropping on a folder/empty space does not advance the counter. Before applying a rename, skip occupied numbers so existing files are never overwritten; advance past the number actually used.
- Tags and counters belong to the current folder, not a global set. Switching folders loads that folder's chips. Store them outside the workshop in `%LOCALAPPDATA%/late_night_workshop/organizer.json`, keyed by canonical folder path, using an atomic replacement write.
- Persist after tag creation/removal and each successful rename; restore on application restart. Reserve/persist the next counter before a rename is finalized so a crash cannot silently reuse a successful number; release that reservation on an ordinary failed rename. An interrupted operation may leave a gap. Report storage errors instead of claiming the tag was saved.
- If an app operation moves/renames a folder, remap stored folder paths for it and its descendants. Copying a folder does not clone its tags. External folder moves are not automatically followed; path-based storage is the Phase 2 scope.
- After a confirmed successful folder-tree Delete, clear active tags and counter history for that folder and all deleted descendants. A newly created folder at the same path starts fresh. On partial deletion, clear only state for confirmed deleted folders; retain state for surviving folders.
- During Rip, remap each surviving child folder and its descendants to their actual new paths as their moves are confirmed, preserving active tags and counter history. Clear the wrapper folder's own state only after the wrapper is confirmed removed. If Rip partially succeeds or wrapper removal fails, update metadata only for confirmed filesystem changes and retain the surviving wrapper's own state.
- Removing and recreating a tag retains its recorded counter for that folder/name. Store counter history separately from the six visible chips so numbering does not restart accidentally.

Acceptance example: in `Coursework/Batch`, use `assignment` through number 5, remove the chip, then recreate it; the next free number continues from 6. Successfully Delete the entire `Batch` folder tree, recreate an empty folder at that path, and create `assignment` there; it starts at 1. During Rip, a tagged child folder moved from `Coursework/Batch/Topics` to `Coursework/Topics` keeps its tags/counters, while the removed `Batch` loses its own state. Verify partial outcomes preserve metadata for folders that remain.

## Proposed component map

Python modules below are under `src/late_night_workshop/`; the proposed icon is under that package's `assets/`. `pyproject.toml` and `packaging/late-night-workshop.spec` are repository-root paths. New modules and symbols are proposed; keep the existing generation pipeline intact.

| Component / files | Responsibility and entry point | Inputs → outputs |
| --- | --- | --- |
| Existing `ui.py` | Mode selector, six buttons with Rip helper text, folder selection, accessible Selected Inputs remove controls, Refresh, tray, tag controls/drop targets; run filesystem work outside the UI thread | UI events → captured action requests; results → refreshed browser/status |
| Existing `workshops.py` | Extend selection to organization entries; reconcile/remap paths while retaining generation validation | Workshop + navigation/selection/change records → coherent folder and selection state |
| New `organizing.py` | `plan_action()` / `execute_plan()` for Delete, Rip, Wrap, copy/paste moves; containment/collisions, per-item outcomes and cut retry records; isolate OS recycling/clipboard adapters | Action + root + sources + destination + parameters → plan → completed/failed/unattempted outcomes and confirmed path mappings |
| New `super_wrap.py` | Pure recursive grouping planner; no UI or filesystem writes | Source relative names + outer folder → deterministic destination mapping or conflicts |
| New `name_tags.py` | Folder tags, six-chip limit, counter allocation, safe rename plan, atomic persistence; remap/clear metadata only for confirmed filesystem changes | Folder + tag event/file target or confirmed move/delete → tag state or rename request |
| New `downloads.py` | Agreed-browser completion-record provider and on-demand one-hour reconciliation; proposed Chrome support unverified until P2-M1; no timers | Provider records + injected current time → eligible existing completed-download records |
| Proposed `assets/recent-downloads-bin.svg` | Custom generated/drawn bin icon bundled with the desktop app | Local asset → accessible tray button |
| Existing `pyproject.toml`, packaging spec | Include icon and any verified OS integration dependency | Source/resources → working Windows build |

Use plain values/functions so grouping, time filtering, and path plans can run on fixtures without opening the UI. Do not build a generic plugin framework, new server, database, AI organizer, global filesystem crawler, or CI/CD system for this phase.

## Phase 2 milestones

Milestones are integration checkpoints following the dependencies below, not claims of implemented behavior. No elapsed-time budget is imposed. P2-M1 records operation/selection contracts and a browser feasibility outcome; a failed browser check blocks P2-M6, not P2-M2–P2-M5.

| Milestone | Depends on | Scope / proposed ownership | Done when |
| --- | --- | --- | --- |
| P2-M1: Operation contracts and download feasibility | Existing Phase 1 baseline | `organizing.py` contract; `downloads.py` provider probe; UI selection design | A temporary-folder example demonstrates a source-to-destination plan and folder selection/navigation are specified. Record the agreed Windows browser (proposed Chrome), version/profile scope, source/fields of actual completion timestamps and final paths, and a real feasibility-check result covering custom locations and pre-launch completed downloads. On failure mark P2-M6 blocked; release the operation/selection contracts for P2-M2–P2-M5. |
| P2-M2: Mode switch, selection, Refresh | P2-M1 selection contract; browser feasibility need not pass | `ui.py`, `workshops.py` | Switch modes without losing state. Select a supported file and a folder in Organize, navigate elsewhere, switch to Make me, and remove the folder via its Selected Inputs control: only it is deselected and Generate becomes available when other requirements are met. Confirm controls work in both modes, parameters persist, and Refresh reflects external additions/deletions while pruning stale selections. |
| P2-M3: Basic organizer end to end | P2-M2 | `organizing.py`, clipboard/recycling adapters, action UI | A disposable workshop exercises all five basic actions and the documented Coursework/Batch Rip example with helper text and collision refusal. Reject folder self/descendant destinations before copy or cut, including external entries, while allowing same-folder file copy with a suffix. For an accepted three-item external cut, force item 2 to fail after item 1 moves: report 1 completed, 2 failed, 3 unattempted; preserve remaining sources, send no full-batch acknowledgment, and retry without re-moving item 1 or deleting a remaining source on destination existence alone. An unsafe cut protocol is rejected before mutation. |
| P2-M4: Recursive Super Wrap | P2-M3 | `super_wrap.py`, integration in organizer/UI | The exact three-file `Cal_1` example produces the documented tree with extensions intact; a deeper example terminates, singleton names stay intact, and duplicate destinations are rejected before mutation. |
| P2-M5: Persistent name tags | P2-M3 | `name_tags.py`, tag UI/drop target | Create six folder-specific tags, reject a seventh, number five files, restart, and continue the counter; a second folder remains independent. Verify the acceptance example in Folder-specific persistent name tags and preserve child tags/counters through Rip, clearing only confirmed deleted/removed folder state, including partial outcomes. |
| P2-M6: Recent-download tray and import | P2-M2; successful P2-M1 browser feasibility check required, otherwise blocked | `downloads.py`, bin icon, tray/import UI | For the agreed Windows browser (proposed Chrome), opening/refreshing lists recorded completed downloads including custom-location and pre-launch downloads, excludes incomplete/cancelled records, filters just-under/at-one-hour records without a timer, removes missing entries, and copies a selected file into the workshop without deleting its source. Completion timestamp/path evidence must pass; computer-wide discovery is future scope. |
| P2-M7: Integrated demo and packaged handoff | P2-M4–P2-M6 passed, including P2-M6 for the agreed browser | Targeted integration fixes, package data, `architecture.md`, `workflow.md`, README | The packaged app runs the walkthrough below, bundles the bin icon, restores tags after restart, and still completes one existing generation path. Implemented documentation matches the build and records verified browser scope. Full Phase 2 handoff cannot be claimed while P2-M6 is blocked or unpassed. |

During later implementation, update `architecture.md` and `workflow.md` alongside each affected milestone, and README when setup or demo instructions change. This planning-only change leaves those current-state documents accurate and unchanged.

## Focused verification and demo

Use a disposable workshop; never rehearse destructive actions on original study materials. Reuse existing tests and use one meaningful example per changed responsibility rather than running the full suite by default.

1. In Organize, select a supported file and a folder, navigate elsewhere, and switch to Make me. Remove the folder using its accessible Selected Inputs control; verify Generate becomes available when other requirements are met, the file stays selected, and Make me parameters persist. Check the same deselect-only control in Organize and retain relative-path labels across navigation.
2. Add/delete a file externally and press Refresh. Confirm the list and stale selections reconcile.
3. Reuse P2-M3's basic-action checks: Copy/Paste a file beside itself with a suffix, reject folder self/descendant copy/cut plans before mutation, and exercise the three-item external cut whose second item fails, including its report, acknowledgment, and safe retry. Wrap `Lectures/a.pdf` and `Labs/b.pdf` as `Coursework/Batch`, then Rip `Batch` into `Coursework/a.pdf` and `Coursework/b.pdf`; confirm the helper text, current-parent behavior, no original-location restoration, and collision refusal. Recycle a disposable file and confirm browser removal.
4. Super Wrap the exact `Cal_1` example. Inspect the output tree and verify all three source contents and extensions are unchanged.
5. Reuse P2-M5's five-drop/restart check and the tag-state acceptance example: recreating `assignment` in the surviving folder continues from 6, while deleting/recreating that folder resets it to 1. Confirm independent folder chips, Rip child-path remapping, and metadata updates limited to confirmed changes on partial Delete/Rip.
6. After successful P2-M1 browser feasibility, open the download tray with real completed-download records from the agreed Windows browser (proposed Chrome), including custom-location and pre-launch downloads. Confirm incomplete/cancelled and missing-file records are excluded. Copy one file into the workshop. Check just-under/at-one-hour records with an injected clock; expiration removes only the entry. Record the browser and verified timestamp/path source. If feasibility failed, mark P2-M6 blocked and continue P2-M2–P2-M5; do not claim full handoff.
7. Run one existing Summary generation through Make me to verify the changed UI boundary still submits the existing request correctly. Do not repeat every generation task or benchmark the app.
8. Launch the packaged build outside the source checkout and check the icon, clipboard/recycle integration, and persisted tags. Record observed outcomes and the agreed browser scope. Claim full P2-M7 handoff only after P2-M6 passes for that browser; computer-wide discovery remains future scope.

## Completion boundary

Phase 2 is complete when all six direct buttons meet the safe operation/partial-cut contracts, selections can be removed in either mode, Make me retains its current behavior, Refresh reconciles filesystem changes, recursive grouping matches the examples, and folder-specific tags/counters survive restart with correct Delete/Rip cleanup. P2-M6 must pass for completed downloads recorded by the agreed Windows demo browser (proposed Chrome, unverified until P2-M1), including custom save locations and pre-launch downloads, using completion timestamps and existing paths with on-demand one-hour filtering and copy-to-workshop. Full P2-M7 handoff requires that pass. Computer-wide discovery is future scope. Planning alone, a UI mockup, or file-timestamp/Downloads-folder approximations do not satisfy the milestones; none are marked complete by this revision.
