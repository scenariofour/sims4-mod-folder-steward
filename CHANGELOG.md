# Changelog

## Unreleased

- Added bilingual repository scaffold.
- Added safety, privacy and AI-assisted workflow specifications.
- Added a read-only `s4mod scan` command with macOS, iCloud and Windows path discovery.
- Added SHA-256 inventory, exact duplicate, same-name conflict, script-depth, archive,
  root-file, empty-directory and symbolic-link checks.
- Added workspace path boundaries that reject absolute paths, traversal, Saves and report writes
  inside Mods.
- Added localized HTML, CSV, JSON and TXT scan reports plus an anonymized `AI_HANDOFF.md`.
- Added snapshot, plan and manifest JSON Schemas.
- Added Inbox staging with ZIP path, link, size, entry-count, nesting and compression-ratio checks;
  RAR and 7Z remain explicit manual-review items.
- Added a dry-run Planner with hash-based install, skip, replace and review decisions.
- Added a transactional Executor with full preflight, per-operation manifests, replacement
  quarantine, post-run scans and automatic rollback after failures or interruption.
- Added manifest-driven Undo with content verification and refusal to overwrite changed files.
- Added interactive `s4mod run --apply` and `s4mod undo` confirmation phrases.
- Kept Scanner, Planner, Executor, Quarantine and Undo as UI-independent core services shared by
  terminal, AI-agent integrations and the PySide6 GUI.
- Added a single-window, three-page PySide6 GUI for automatic discovery, drag-and-drop input,
  three-group results, whole-Plan approval, optional full backup, result access and Undo.
- Added reversible `backup` Plan operations for SHA-256-identical duplicate copies.
- Added one anonymized AI check ZIP and clipboard prompt without a built-in AI or network client.
- Added a shared workflow service used by both CLI and GUI.
- Added PyInstaller configuration and Windows/macOS package automation.
