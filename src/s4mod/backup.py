from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .hashing import sha256_file
from .models import FileKind, ScanSnapshot
from .paths import WorkspacePaths, safe_join, validate_run_directory
from .storage import write_json_new


class BackupError(RuntimeError):
    """Raised when a complete Mods backup cannot be created safely."""


@dataclass(frozen=True, slots=True)
class BackupSummary:
    created_at: str
    relative_path: str
    files: int
    bytes: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def estimate_backup_bytes(snapshot: ScanSnapshot) -> int:
    return sum(record.size for record in snapshot.files)


def _preflight_files(
    workspace: WorkspacePaths,
    snapshot: ScanSnapshot,
) -> tuple[list[Path], list[Path]]:
    found: list[Path] = []
    directories: list[Path] = []
    for current_text, directory_names, file_names in os.walk(
        workspace.mods_root,
        followlinks=False,
    ):
        current = Path(current_text)
        if current != workspace.mods_root:
            directories.append(current)
        for name in [*directory_names, *file_names]:
            path = current / name
            if path.is_symlink():
                raise BackupError(
                    "A complete backup cannot include symbolic links. Remove them or scan again."
                )
        for name in file_names:
            path = current / name
            if not path.is_file():
                raise BackupError(f"A complete backup found a non-regular file: {name}")
            found.append(path)

    by_relative = {record.relative_path: record for record in snapshot.files}
    found_relative = {path.relative_to(workspace.mods_root).as_posix() for path in found}
    if found_relative != set(by_relative):
        raise BackupError(
            "Mods changed after the scan. Check the folder again before backing it up."
        )
    for path in found:
        relative = path.relative_to(workspace.mods_root).as_posix()
        record = by_relative[relative]
        stat_result = path.stat()
        if stat_result.st_size != record.size or stat_result.st_mtime_ns != record.modified_ns:
            raise BackupError(f"Mods changed after the scan: {relative}")
        if record.kind in {FileKind.PACKAGE, FileKind.TS4SCRIPT} and (
            record.sha256 is None or sha256_file(path) != record.sha256
        ):
            raise BackupError(f"Mods content changed after the scan: {relative}")
    return (
        sorted(found, key=lambda path: path.as_posix().casefold()),
        sorted(directories, key=lambda path: path.as_posix().casefold()),
    )


def create_full_mods_backup(
    workspace: WorkspacePaths,
    run_directory: Path,
    snapshot: ScanSnapshot,
) -> BackupSummary:
    run_directory = validate_run_directory(run_directory, workspace, must_exist=True)
    destination = safe_join(run_directory, "full-mods-backup")
    partial = safe_join(run_directory, "full-mods-backup.partial")
    if destination.exists() or partial.exists():
        raise FileExistsError("This run already has a complete Mods backup or partial backup.")
    files, directories = _preflight_files(workspace, snapshot)
    required = sum(path.stat().st_size for path in files)
    if shutil.disk_usage(run_directory).free < required:
        raise BackupError(
            f"Not enough free space for the complete backup ({required} bytes required)."
        )

    partial.mkdir()
    try:
        for source_directory in directories:
            relative = source_directory.relative_to(workspace.mods_root)
            safe_join(partial, relative).mkdir(parents=True, exist_ok=True)
        for source in files:
            relative = source.relative_to(workspace.mods_root)
            target = safe_join(partial, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        os.replace(partial, destination)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise

    summary = BackupSummary(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        relative_path="full-mods-backup",
        files=len(files),
        bytes=required,
    )
    write_json_new(run_directory / "full-backup.json", summary.to_dict())
    return summary
