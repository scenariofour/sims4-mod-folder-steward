from __future__ import annotations

from pathlib import Path

import pytest

from s4mod.paths import (
    PathSafetyError,
    build_workspace_paths,
    candidate_mods_paths,
    safe_join,
    validate_inbox_directory,
    validate_relative_path,
    validate_report_directory,
    validate_run_directory,
)


def test_candidate_paths_cover_macos_icloud_and_windows_onedrive(tmp_path: Path) -> None:
    onedrive = tmp_path / "OneDrive"
    candidates = candidate_mods_paths(tmp_path, {"OneDrive": str(onedrive)})

    assert tmp_path / "Documents/Electronic Arts/The Sims 4/Mods" in candidates
    assert (
        tmp_path
        / "Library/Mobile Documents/com~apple~CloudDocs/Documents/Electronic Arts/The Sims 4/Mods"
        in candidates
    )
    assert onedrive / "Documents/Electronic Arts/The Sims 4/Mods" in candidates


@pytest.mark.parametrize(
    "value",
    ["", "../outside", "folder/../outside", "/absolute", r"C:\\Users\\name", r"\\server\\share"],
)
def test_relative_path_rejects_absolute_and_traversal(value: str) -> None:
    with pytest.raises(PathSafetyError):
        validate_relative_path(value)


def test_safe_join_keeps_result_inside_root(tmp_path: Path) -> None:
    assert safe_join(tmp_path, "Creator/file.package") == tmp_path / "Creator/file.package"


def test_safe_join_rejects_internal_symlink_component(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "link").symlink_to(target, target_is_directory=True)

    with pytest.raises(PathSafetyError):
        safe_join(tmp_path, "link/file.package")


def test_report_directory_rejects_mods_saves_and_outside(tmp_path: Path) -> None:
    mods = tmp_path / "Game" / "Mods"
    mods.mkdir(parents=True)
    workspace = build_workspace_paths(mods)

    valid = tmp_path / "Game" / "S4ModSteward" / "runs" / "scan-1"
    assert validate_report_directory(valid, workspace) == valid

    with pytest.raises(PathSafetyError):
        validate_report_directory(mods / "reports", workspace)
    with pytest.raises(PathSafetyError):
        validate_report_directory(tmp_path / "Game" / "Saves" / "reports", workspace)
    with pytest.raises(PathSafetyError):
        validate_report_directory(tmp_path / "outside", workspace)


def test_report_directory_rejects_symlink_component(tmp_path: Path) -> None:
    mods = tmp_path / "Game" / "Mods"
    target = tmp_path / "Game" / "state-target"
    mods.mkdir(parents=True)
    target.mkdir()
    link = tmp_path / "Game" / "state-link"
    link.symlink_to(target, target_is_directory=True)
    workspace = build_workspace_paths(mods)

    with pytest.raises(PathSafetyError):
        validate_report_directory(link / "run", workspace)


def test_inbox_and_run_directories_stay_in_their_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "Game"
    mods = root / "Mods"
    inbox = root / "Inbox"
    saves_inbox = root / "Saves" / "Inbox"
    mods.mkdir(parents=True)
    inbox.mkdir()
    saves_inbox.mkdir(parents=True)
    workspace = build_workspace_paths(mods)

    assert validate_inbox_directory(inbox, workspace) == inbox
    with pytest.raises(PathSafetyError):
        validate_inbox_directory(mods, workspace)
    with pytest.raises(PathSafetyError):
        validate_inbox_directory(saves_inbox, workspace)
    with pytest.raises(PathSafetyError):
        validate_inbox_directory(tmp_path, workspace)

    run = root / "S4ModSteward" / "runs" / "run-test"
    assert validate_run_directory(run, workspace, must_exist=False) == run
    with pytest.raises(PathSafetyError):
        validate_run_directory(root / "S4ModSteward" / "runs", workspace, must_exist=False)
    with pytest.raises(PathSafetyError):
        validate_run_directory(inbox / "run-test", workspace, must_exist=False)


def test_broken_symlink_component_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "Game"
    mods = root / "Mods"
    mods.mkdir(parents=True)
    broken = root / "broken-link"
    broken.symlink_to(root / "missing", target_is_directory=True)
    workspace = build_workspace_paths(mods)

    with pytest.raises(PathSafetyError):
        validate_report_directory(broken / "report", workspace)


def test_nested_saves_paths_are_always_rejected(tmp_path: Path) -> None:
    root = tmp_path / "Game"
    mods = root / "Mods"
    nested_inbox = root / "Selected" / "Saves" / "Inbox"
    mods.mkdir(parents=True)
    nested_inbox.mkdir(parents=True)
    workspace = build_workspace_paths(mods)

    with pytest.raises(PathSafetyError, match="Saves"):
        validate_inbox_directory(nested_inbox, workspace)
    with pytest.raises(PathSafetyError, match="Saves"):
        validate_report_directory(nested_inbox / "report", workspace)

    disguised_mods = tmp_path / "The Sims 4" / "Saves" / "Slot" / "Mods"
    disguised_mods.mkdir(parents=True)
    with pytest.raises(PathSafetyError, match="Saves"):
        build_workspace_paths(disguised_mods)
