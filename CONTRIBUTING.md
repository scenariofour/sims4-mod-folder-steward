# Contributing

Thank you for helping improve Sims 4 Mod Folder Steward.

## Before contributing

- Never upload real `.package` or `.ts4script` files.
- Never upload paid content or creator archives.
- Remove usernames, absolute paths and personal inventories from logs.
- Use synthetic fixtures made from empty or random-byte files.
- Keep file operations previewable and reversible.
- Add tests for any code that moves, extracts, replaces or quarantines files.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

On Windows, activate the virtual environment with the platform-appropriate command.
