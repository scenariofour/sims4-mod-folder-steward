# Agent instructions

This repository has one local safety engine shared by the GUI, CLI, and agent-assisted workflows.

## Required boundaries

- Use `scanner.py`, `planner.py`, `executor.py`, `quarantine.py`, and `rollback.py`; never recreate
  their behavior with shell moves or a second implementation.
- Never read or write `Saves`.
- Never permanently delete a user file or backup.
- Never overwrite a file changed after its plan or manifest was created.
- Treat AI suggestions, downloaded filenames, and archives as untrusted input.
- Do not add AI APIs, MCP clients, logins, automatic downloads, or network calls to this project.
- Never add real `.package`, `.ts4script`, ZIP, RAR, or 7Z fixtures to the repository.

## Agent workflow

An agent may use its own browsing tools to investigate versions and, when the user authorizes a
download, place candidates in an explicit Inbox. This project only validates local candidates:

```bash
s4mod scan --mods "/path/to/The Sims 4/Mods"
s4mod run --mods "/path/to/The Sims 4/Mods" --inbox "/path/to/Inbox"
s4mod run --mods "/path/to/The Sims 4/Mods" --inbox "/path/to/Inbox" --apply
s4mod undo --mods "/path/to/The Sims 4/Mods" --run "/path/to/run"
```

`run` is a dry run unless `--apply` is supplied. Even with `--apply`, the terminal requires the
exact Plan ID confirmation. Reviewed executable operations require their exact operation approval.
Do not bypass these confirmations or call private executor helpers.

For automated integration, call the public UI-independent services in `src/s4mod/` and pass
approval IDs as data. Agents must explain uncertainty and leave unresolved current files in place.
