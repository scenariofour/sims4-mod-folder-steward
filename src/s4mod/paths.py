from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

STATE_DIRECTORY_NAME = "S4ModSteward"
FORBIDDEN_WORKSPACE_DIRECTORIES = frozenset({"saves"})


class PathSafetyError(ValueError):
    """Raised when a requested path leaves the selected workspace."""


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    workspace_root: Path
    mods_root: Path
    state_root: Path


def candidate_mods_paths(
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    home = (home or Path.home()).expanduser()
    environ = environ or os.environ
    candidates = [
        home / "Documents" / "Electronic Arts" / "The Sims 4" / "Mods",
        home
        / "Library"
        / "Mobile Documents"
        / "com~apple~CloudDocs"
        / "Documents"
        / "Electronic Arts"
        / "The Sims 4"
        / "Mods",
    ]
    for variable in ("OneDrive", "OneDriveConsumer"):
        value = environ.get(variable)
        if value:
            candidates.append(Path(value) / "Documents" / "Electronic Arts" / "The Sims 4" / "Mods")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return tuple(unique)


def discover_mods_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return validate_mods_path(explicit)
    for candidate in candidate_mods_paths():
        if candidate.is_dir():
            return validate_mods_path(candidate)
    raise FileNotFoundError("Could not find The Sims 4 Mods folder. Specify it with --mods.")


def validate_mods_path(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.exists():
        raise FileNotFoundError(f"Mods folder does not exist: {expanded}")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(f"Mods path is not a directory: {resolved}")
    if resolved.name.casefold() != "mods":
        raise PathSafetyError("The selected folder must be named 'Mods'.")
    if any(parent.name.casefold() in FORBIDDEN_WORKSPACE_DIRECTORIES for parent in resolved.parents):
        raise PathSafetyError("The selected Mods folder cannot be inside Saves.")
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise PathSafetyError("Refusing to use a broad filesystem directory as Mods.")
    return resolved


def build_workspace_paths(mods_root: Path) -> WorkspacePaths:
    mods_root = validate_mods_path(mods_root)
    workspace_root = mods_root.parent.resolve(strict=True)
    return WorkspacePaths(
        workspace_root=workspace_root,
        mods_root=mods_root,
        state_root=workspace_root / STATE_DIRECTORY_NAME,
    )


def is_within(path: Path, root: Path, *, allow_equal: bool = True) -> bool:
    candidate = path.resolve(strict=False)
    boundary = root.resolve(strict=False)
    return (allow_equal and candidate == boundary) or boundary in candidate.parents


def require_within(path: Path, root: Path, *, label: str = "path") -> Path:
    resolved = path.resolve(strict=False)
    if not is_within(resolved, root):
        raise PathSafetyError(f"{label} leaves the selected workspace: {path}")
    return resolved


def validate_relative_path(value: str | Path) -> tuple[str, ...]:
    raw = str(value)
    if not raw or "\x00" in raw:
        raise PathSafetyError("Relative path is empty or contains a null byte.")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if (
        raw.startswith(("\\\\", "//"))
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
    ):
        raise PathSafetyError(f"Absolute paths are not allowed: {raw}")
    parts = tuple(part for part in re.split(r"[\\/]+", raw) if part not in {"", "."})
    if not parts or any(part == ".." for part in parts):
        raise PathSafetyError(f"Path traversal is not allowed: {raw}")
    return parts


def safe_join(root: Path, relative: str | Path) -> Path:
    parts = validate_relative_path(relative)
    candidate = root.joinpath(*parts)
    ensure_no_symlink_components(candidate, root)
    return require_within(candidate, root)


def ensure_no_symlink_components(path: Path, root: Path) -> None:
    root = root.resolve(strict=True)
    lexical = Path(os.path.abspath(path.expanduser()))
    require_within(path, root)
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current = current / part
        if current.is_symlink() and is_within(current.parent.resolve(strict=False), root):
            raise PathSafetyError(f"Symlink path components are not allowed: {current}")


def validate_report_directory(path: Path, workspace: WorkspacePaths) -> Path:
    ensure_no_symlink_components(path.parent, workspace.workspace_root)
    candidate = require_within(path, workspace.workspace_root, label="report directory")
    if is_within(candidate, workspace.mods_root):
        raise PathSafetyError("Reports cannot be written inside the Mods folder.")
    try:
        first_part = candidate.relative_to(workspace.workspace_root).parts[0].casefold()
    except (IndexError, ValueError):
        raise PathSafetyError("Reports cannot replace the workspace root.") from None
    relative_parts = {part.casefold() for part in candidate.relative_to(workspace.workspace_root).parts}
    if first_part in FORBIDDEN_WORKSPACE_DIRECTORIES or relative_parts & FORBIDDEN_WORKSPACE_DIRECTORIES:
        raise PathSafetyError("Reports cannot be written inside Saves.")
    if candidate.exists():
        raise FileExistsError(f"Report directory already exists: {candidate}")
    return candidate


def validate_inbox_directory(path: Path, workspace: WorkspacePaths) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Inbox does not exist: {path}")
    ensure_no_symlink_components(path, workspace.workspace_root)
    candidate = require_within(path, workspace.workspace_root, label="Inbox")
    if not candidate.is_dir():
        raise NotADirectoryError(f"Inbox is not a directory: {candidate}")
    if is_within(candidate, workspace.mods_root):
        raise PathSafetyError("Inbox cannot be inside the Mods folder.")
    relative = candidate.relative_to(workspace.workspace_root)
    if {part.casefold() for part in relative.parts} & FORBIDDEN_WORKSPACE_DIRECTORIES:
        raise PathSafetyError("Inbox cannot be inside Saves.")
    return candidate


def validate_run_directory(
    path: Path,
    workspace: WorkspacePaths,
    *,
    must_exist: bool,
) -> Path:
    runs_root = workspace.state_root / "runs"
    check_from = path if path.exists() else path.parent
    ensure_no_symlink_components(check_from, workspace.workspace_root)
    candidate = require_within(path, runs_root, label="run directory")
    if candidate == runs_root.resolve(strict=False):
        raise PathSafetyError("A run must use its own directory below the runs folder.")
    if must_exist:
        if not candidate.exists():
            raise FileNotFoundError(f"Run directory does not exist: {candidate}")
        if not candidate.is_dir():
            raise NotADirectoryError(f"Run path is not a directory: {candidate}")
    elif candidate.exists():
        raise FileExistsError(f"Run directory already exists: {candidate}")
    return candidate
