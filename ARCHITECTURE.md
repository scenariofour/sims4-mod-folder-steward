# Architecture

## Shared core services and entry-point adapters

There is one local safety engine, not one implementation per interface. The five stateful core
services remain independent and UI-agnostic:

- `scanner.py`: read-only inventory and findings
- `planner.py`: evidence-based, non-executing plans
- `executor.py`: preflighted, manifest-backed apply
- `quarantine.py`: deterministic reversible storage paths
- `rollback.py`: manifest-backed undo

The terminal CLI, the three-page PySide6 GUI, and local AI-agent integrations call these same
services. Entry points may collect paths, display translated results, and ask for exact
confirmations; they must not copy scanning, planning, execution, quarantine, or undo rules.
Approval is passed into the core as data (`approved_operation_ids` and the selected plan ID).
`workflow.py` shares scan → staging → plan → report orchestration, so entry points do not duplicate
that sequence either.

```text
Terminal CLI ─┐
PySide6 GUI  ─┼─→ Scanner → Planner → Executor → Quarantine
AI Agent     ─┘                         └──────→ Undo
```

Core modules never import `argparse`, PySide6, clipboard/browser helpers, network clients, or agent
frameworks. This boundary keeps safety behavior identical across all three entry points.

## Safety invariants

These rules are requirements, not preferences:

- `scan` never writes inside `Mods` and never traverses `Saves`.
- The selected `Mods` directory defines one Sims 4 workspace: its parent directory.
- Generated state must remain under `<SIMS4_WORKSPACE>/S4ModSteward/`.
- Absolute paths, drive-qualified paths, `..`, and paths resolved outside the workspace are rejected.
- Symbolic links are not followed during a scan. Write operations reject symlink path components.
- `resource.cfg` is protected and is never proposed as an operation source or destination.
- `.package`, `.ts4script`, and creator folder names are immutable.
- Same-name files with different SHA-256 values always require review.
- No operation permanently deletes a user file.
- No network access is used in the v0.1 command path.

## Public command surface

```text
s4mod scan [--mods PATH] [--lang en|zh-CN] [--output PATH]
s4mod run [--mods PATH] [--inbox PATH] [--lang en|zh-CN] [--profile neutral|en|zh-CN] [--apply]
s4mod undo --mods PATH --run RUN_DIRECTORY [--lang en|zh-CN]
```

The scan command is read-only with respect to the Mods directory. Reports are written to a newly
created run directory. Existing report directories are not overwritten.

## Trust boundaries

| Area | Read | Write | Notes |
| --- | --- | --- | --- |
| `<MODS_FOLDER>` | Scanner and verified backup reads | Confirmed Executor only | Symlinks are never followed |
| `<SIMS4_WORKSPACE>/Saves` | Never | Never | Explicitly forbidden |
| `<SIMS4_WORKSPACE>/S4ModSteward` | Local state | Reports, plans, quarantine, manifests | All writes remain here unless a confirmed operation targets Mods |
| Inbox | Explicit user-selected read | Run staging only | GUI may read an external Inbox; CLI keeps it inside the workspace |
| Repository resources | Locales, profiles, schemas | Never at runtime | Bundled, versioned input |
| Network | Never | Never | Out of scope for v0.1 |

The GUI treats dropped paths as explicit user-selected input. It may read a selected Inbox outside
the workspace, but all staging copies remain inside the new run directory. Only the validated
Executor may write to Mods.

`paths.py` is the single entry point for path discovery and validation. Both POSIX and Windows path
syntax are checked even when the program is running on the other platform, so a crafted drive path
or backslash traversal cannot be interpreted later as a safe relative path.

## Data flow

```text
selected Mods path
    → boundary validation
    → non-following filesystem walk
    → SHA-256 inventory
    → duplicate/conflict/depth/archive findings
    → stable snapshot model
    → localized HTML / CSV / JSON / TXT
    → redaction pass
    → AI_HANDOFF.md
```

The scanner stores only paths relative to `<MODS_FOLDER>`. Absolute paths exist only in process
memory for local filesystem access and are passed through `PathRedactor` before report output.

## Internal modules

- `paths.py`: macOS/Windows discovery, workspace boundaries, safe relative path joins
- `models.py`: typed inventory, finding, summary, and snapshot models
- `hashing.py`: streaming SHA-256 calculation
- `scanner.py`: read-only, non-symlink-following Mods inspection
- `matcher.py`: exact hash duplicates and same-name/different-hash conflicts
- `localization.py`: locale and folder-profile loading
- `reports.py`: atomic HTML, CSV, JSON, TXT, and AI handoff output
- `privacy.py`: home, username, Mods, workspace, and run-path redaction
- `archives.py`: Phase 2 safe archive inspection and extraction
- `planner.py`: Phase 2 evidence-based operations
- `executor.py`: Phase 2 confirmed transactional file operations
- `quarantine.py`: Phase 2 reversible storage
- `rollback.py`: Phase 2 manifest-driven undo
- `workflow.py`: UI-independent run orchestration shared by CLI and GUI
- `backup.py`: verified optional full Mods copy inside a run
- `ai_bundle.py`: allowlisted anonymized reports packaged into one ZIP
- `gui.py`: three-page PySide6 adapter; presentation and approval collection only
- `organizer.py`: Phase 2 stable outer category IDs

## Snapshot format

`schemas/snapshot.schema.json` is the public contract for `report.json`.

Each file record contains:

```json
{
  "relative_path": "CreatorFolder/example.package",
  "name": "example.package",
  "kind": "package",
  "size": 1234,
  "sha256": "64 lowercase hexadecimal characters",
  "modified_ns": 0,
  "folder_depth": 1
}
```

Hashes are calculated for `.package` and `.ts4script` files. Archive and other-file records do not
need a hash in Phase 1. Findings use stable codes; their display text is localized at report time.

## Plan format

`schemas/plan.schema.json` defines a dry-run document. Every operation has a UUID, stable action,
run-relative staging source, Mods-relative destination, reason, hashes, evidence, and
`requires_review` flag. A plan is never authority to execute itself. The executor re-resolves paths,
re-checks hashes, and accepts only approval IDs collected by an entry point after an explicit
confirmation.

The `backup` action is the only Plan operation whose source is Mods-relative rather than staging
relative. It is produced only for SHA-256-identical duplicates, preserves one deterministic matching
file, and moves each redundant copy into `quarantine/duplicates/`. It never deletes the copy.

## Manifest and undo format

`schemas/manifest.schema.json` defines the Phase 2 applied-run record. A run directory will contain:

```text
before.json
plan.json
manifest.json
after.json
quarantine/
undo_after.json  # only after Undo
```

The manifest begins in `applying` state and records each completed operation before the next one.
Undo processes completed operations in reverse order and refuses to overwrite an existing target.
If apply fails, the executor uses the same reverse procedure automatically. A failed rollback stays
recorded as `rollback_failed` for manual recovery; it is never hidden.

## Quarantine structure

Replacement quarantine paths preserve the original Mods-relative path and isolate operation IDs:

```text
<RUN_FOLDER>/quarantine/replaced/<operation-id>/<original-relative-path>
```

Name collisions are not solved by overwriting or silently adding an arbitrary suffix. They stop the
operation unless the manifest already proves that the existing target is the same quarantined file.

## Stable category IDs and folder profiles

Folder display names are localized, but these IDs remain stable:

```text
core
ui
school
career
relationships
food
gameplay
adult_gameplay
cas
body_details
animations_props
poses
manual_review
```

The `en`, `zh-CN`, and `neutral` YAML profiles map IDs to tool-created outer folders. A language
change never renames an original filename or creator folder. `neutral` preserves existing structure.

## Localization

Internal codes, schemas, and JSON keys stay language-neutral. `locales/en.json` and
`locales/zh-CN.json` must contain identical key sets. CLI labels, HTML, CSV headers, TXT, and the AI
handoff are rendered through the selected `Translator`.

## AI handoff privacy

`AI_HANDOFF.md` is recommendations-only input. Before writing, reports replace:

- run directory → `<RUN_FOLDER>`
- Mods directory → `<MODS_FOLDER>`
- Sims 4 workspace → `<SIMS4_WORKSPACE>`
- home directory → `<HOME>`
- local username → `<USER>`

The handoff may contain relative filenames and hash evidence, but never file contents, credentials,
or executable operations. AI suggestions must be parsed as untrusted input and revalidated by the
local Phase 2 planner.

## Desktop GUI boundary

The GUI contains no Scanner, Planner, Executor, Quarantine, Undo, archive, hashing, or backup file
logic. It accepts recognized local paths, groups existing findings into three plain-language views,
collects one whole-Plan approval, and calls public services. Advanced details are a collapsed view of
existing JSON data.

The GUI contains no AI API, MCP client, login flow, web search, downloader, plugin, backup deletion,
animation, or additional window. “Let AI help” copies a prompt; export creates one local ZIP from an
allowlist of anonymized reports.
