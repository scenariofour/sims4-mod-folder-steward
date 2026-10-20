[**English**](./README.md) | [简体中文](./README.zh-CN.md)

# Sims 4 Mod Folder Steward

A local, beginner-friendly desktop tool that checks, plans, backs up, applies, and undoes changes to
The Sims 4 Mods folder.

> **Status:** v0.1 beta candidate. Use a test copy before relying on any file-management tool with
> an important Mods library.

## The simple workflow

The PySide6 app has one window and three pages:

1. **Start:** it finds the usual Mods folder automatically. Drop a Mods folder, optional Inbox,
   ZIP, `.package`, or `.ts4script`, choose languages, and select **Check my Mods**.
2. **Check results:** see only **Safe to handle**, **Needs your approval**, and **Leave for now**.
   Technical evidence stays inside expandable advanced details.
3. **Confirm & recover:** review totals, optionally make a complete Mods backup, approve the whole
   Plan once, then open the result or undo the run.

Unknown current files stay where they are. Unknown Inbox files stay in the run’s review area and
are not installed.

## Safety promises

- Read-only scan before every Plan
- Dry run by default in the CLI
- Exact duplicate copies may be moved to a reversible run backup
- Install, replacement, and organization changes require whole-Plan approval
- Replaced originals are quarantined before the new file is installed
- Optional complete Mods backup with a space estimate
- Hash and path checks immediately before every operation and Undo
- No permanent deletion and no GUI control for deleting backups
- No reads or writes in `Saves`
- No network access, login, AI API, MCP, automatic download, or plugin system

## Install from source

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e .
s4mod-gui
```

CLI commands remain available for terminal and agent users:

```bash
s4mod scan --mods "/path/to/Mods"
s4mod run --mods "/path/to/Mods" --inbox "/path/to/Inbox"
s4mod run --mods "/path/to/Mods" --inbox "/path/to/Inbox" --apply
s4mod undo --mods "/path/to/Mods" --run "/path/to/run"
```

See [Getting started](./docs/en/getting-started.md) and [Agent instructions](./AGENTS.md).

## AI-assisted review

The GUI exports one `AI_CHECK_*.zip` containing anonymized reports and a safe prompt. Attach that
single ZIP to an AI assistant. The app does not contact an AI service. An agent may use its own
browsing tools, but downloaded candidates still return through the local Planner and Executor.

No real mod contents are included in the AI ZIP. See
[AI-assisted workflow](./docs/en/ai-assisted-workflow.md).

## Build desktop apps

Windows and macOS must be built separately:

```bash
python -m pip install -e ".[dev]"
pyinstaller --noconfirm --clean packaging/s4mod-steward.spec
```

The repository includes a Windows/macOS packaging workflow. Local development builds are unsigned;
see [packaging notes](./packaging/README.md).

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

Tests use synthetic bytes only. The repository must never include real mods, paid content, user
inventories, credentials, private computer paths, or private reference material.

Made by [Iris](https://iris-li-homepage.vercel.app/). The case study is in
[RIRRI'S](https://rirris-world.vercel.app/#/work/sims4-steward), Iris's 3D portfolio.

Licensed under the [MIT License](./LICENSE). This unofficial fan-made utility is not affiliated
with Electronic Arts, Maxis, or The Sims.
