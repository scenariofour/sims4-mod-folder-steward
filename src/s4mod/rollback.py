from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from .hashing import sha256_file
from .models import (
    ManifestOperation,
    ManifestStatus,
    OperationStatus,
    PlanAction,
    RunManifest,
    run_manifest_from_dict,
)
from .paths import (
    WorkspacePaths,
    ensure_no_symlink_components,
    is_within,
    safe_join,
    validate_run_directory,
)
from .scanner import scan_mods
from .storage import read_json_object, write_json_atomic

BeforeOperation = Callable[[ManifestOperation], None]


class UndoError(RuntimeError):
    """Raised when a recorded run cannot be safely undone."""


def _error_text(error: BaseException) -> str:
    return str(error) or error.__class__.__name__


def _regular_with_hash(path: Path, digest: str, *, label: str) -> None:
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise UndoError(f"{label} is not a regular, non-symlink file: {path}")
    if sha256_file(path) != digest:
        raise UndoError(f"{label} hash changed: {path}")


def _paths(
    operation: ManifestOperation,
    run_directory: Path,
    workspace: WorkspacePaths,
) -> tuple[Path, Path, Path | None]:
    if operation.action == PlanAction.BACKUP:
        source = safe_join(workspace.mods_root, operation.source)
    else:
        source = safe_join(run_directory, operation.source)
        if not is_within(source, run_directory / "staging", allow_equal=False):
            raise UndoError("Manifest source leaves this run's staging directory.")
    destination = safe_join(workspace.mods_root, operation.destination)
    quarantine = (
        safe_join(run_directory, operation.quarantine_path)
        if operation.quarantine_path is not None
        else None
    )
    return source, destination, quarantine


def _preflight(
    operation: ManifestOperation,
    run_directory: Path,
    workspace: WorkspacePaths,
) -> None:
    source, destination, quarantine = _paths(operation, run_directory, workspace)
    if operation.action == PlanAction.BACKUP:
        if source.exists() or source.is_symlink():
            raise UndoError(f"Duplicate restore path is occupied: {operation.source}")
        if quarantine is None:
            raise UndoError("Duplicate backup manifest data is incomplete.")
        ensure_no_symlink_components(quarantine, run_directory)
        _regular_with_hash(quarantine, operation.source_sha256, label="Backed-up duplicate")
        return
    ensure_no_symlink_components(destination, workspace.mods_root)
    ensure_no_symlink_components(source.parent, run_directory)
    if source.exists() or source.is_symlink():
        raise UndoError(f"Undo staging path is occupied: {operation.source}")
    _regular_with_hash(destination, operation.source_sha256, label="Applied destination")
    if operation.action == PlanAction.INSTALL:
        return
    if (
        operation.action != PlanAction.REPLACE
        or quarantine is None
        or operation.target_before_sha256 is None
    ):
        raise UndoError("Replacement manifest data is incomplete.")
    ensure_no_symlink_components(quarantine, run_directory)
    _regular_with_hash(
        quarantine,
        operation.target_before_sha256,
        label="Quarantined original",
    )


def _undo_operation(
    operation: ManifestOperation,
    run_directory: Path,
    workspace: WorkspacePaths,
) -> None:
    source, destination, quarantine = _paths(operation, run_directory, workspace)
    if operation.action == PlanAction.BACKUP:
        assert quarantine is not None
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(quarantine, destination)
        return
    source.parent.mkdir(parents=True, exist_ok=True)
    os.replace(destination, source)
    if operation.action == PlanAction.INSTALL:
        return
    assert quarantine is not None
    try:
        os.replace(quarantine, destination)
    except BaseException:
        os.replace(source, destination)
        raise


def _restore_applied_state(
    operation: ManifestOperation,
    run_directory: Path,
    workspace: WorkspacePaths,
) -> None:
    source, destination, quarantine = _paths(operation, run_directory, workspace)
    if operation.action == PlanAction.BACKUP:
        assert quarantine is not None
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        os.replace(destination, quarantine)
        return
    if operation.action == PlanAction.INSTALL:
        os.replace(source, destination)
        return
    assert quarantine is not None
    quarantine.parent.mkdir(parents=True, exist_ok=True)
    os.replace(destination, quarantine)
    try:
        os.replace(source, destination)
    except BaseException:
        os.replace(quarantine, destination)
        raise


def load_manifest(run_directory: Path, workspace: WorkspacePaths) -> RunManifest:
    run_directory = validate_run_directory(run_directory, workspace, must_exist=True)
    return run_manifest_from_dict(read_json_object(run_directory / "manifest.json"))


def undo_run(
    run_directory: Path,
    workspace: WorkspacePaths,
    *,
    before_operation: BeforeOperation | None = None,
) -> RunManifest:
    run_directory = validate_run_directory(run_directory, workspace, must_exist=True)
    manifest_path = run_directory / "manifest.json"
    manifest = run_manifest_from_dict(read_json_object(manifest_path))
    if manifest.status != ManifestStatus.APPLIED:
        raise UndoError(f"Only an applied run can be undone (status: {manifest.status}).")

    completed = [
        operation
        for operation in manifest.operations
        if operation.status == OperationStatus.COMPLETED
    ]
    for operation in completed:
        _preflight(operation, run_directory, workspace)

    undone: list[ManifestOperation] = []
    current: ManifestOperation | None = None
    try:
        for current in reversed(completed):
            if before_operation is not None:
                before_operation(current)
            _undo_operation(current, run_directory, workspace)
            current.status = OperationStatus.ROLLED_BACK
            undone.append(current)
            write_json_atomic(manifest_path, manifest.to_dict())
        after = scan_mods(workspace.mods_root, language="en")
        write_json_atomic(run_directory / "undo_after.json", after.to_dict())
        manifest.status = ManifestStatus.ROLLED_BACK
        write_json_atomic(manifest_path, manifest.to_dict())
        return manifest
    except (Exception, KeyboardInterrupt) as error:
        if current is not None:
            current.error = _error_text(error)
        recovery_error: BaseException | None = None
        for operation in reversed(undone):
            try:
                _restore_applied_state(operation, run_directory, workspace)
                operation.status = OperationStatus.COMPLETED
            except (Exception, KeyboardInterrupt) as candidate:  # noqa: BLE001
                operation.error = _error_text(candidate)
                recovery_error = candidate
                break
            finally:
                write_json_atomic(manifest_path, manifest.to_dict())
        manifest.status = ManifestStatus.ROLLBACK_FAILED
        write_json_atomic(manifest_path, manifest.to_dict())
        detail = _error_text(error)
        if recovery_error is not None:
            detail += f"; undo recovery also failed: {_error_text(recovery_error)}"
        raise UndoError(f"Undo failed: {detail}") from error
