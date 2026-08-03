# Project files

## Root

- `README.md`: English project homepage
- `README.zh-CN.md`: Simplified Chinese homepage
- `LICENSE`: MIT License
- `ARCHITECTURE.md`: internal structure and trust boundaries
- `ROADMAP.md`: planned versions
- `SECURITY.md`: private security reporting guidance
- `CONTRIBUTING.md`: contribution rules
- `pyproject.toml`: Python package metadata
- `AGENTS.md`: shared-engine and safety rules for coding agents
- `packaging/`: PyInstaller entry point, cross-platform spec, and build notes

## Source

- `src/s4mod/`: application code
- `src/s4mod/gui.py`: three-page PySide6 entry point
- `src/s4mod/workflow.py`: shared CLI/GUI run orchestration
- `src/s4mod/backup.py`: optional complete Mods backup
- `src/s4mod/ai_bundle.py`: anonymized single-ZIP export
- `locales/`: interface translations
- `folder_profiles/`: localized outer-folder systems

## Documentation and prompts

- `docs/en/` and `docs/zh-CN/`: user documentation
- `prompts/en/` and `prompts/zh-CN/`: safe AI prompts

## Tests and automation

- `tests/`: synthetic tests only
- `.github/workflows/`: continuous integration
- `.github/workflows/package.yml`: native Windows/macOS packaging
- `.github/ISSUE_TEMPLATE/`: structured bug reports
