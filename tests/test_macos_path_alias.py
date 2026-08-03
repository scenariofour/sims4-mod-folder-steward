from __future__ import annotations

from pathlib import Path

from s4mod.paths import build_workspace_paths, validate_report_directory


def test_system_level_path_alias_does_not_look_like_workspace_symlink(tmp_path: Path) -> None:
    mods = tmp_path / "Game" / "Mods"
    mods.mkdir(parents=True)
    workspace = build_workspace_paths(mods)
    requested = tmp_path / "Game" / "Report"

    assert validate_report_directory(requested, workspace) == requested.resolve(strict=False)
