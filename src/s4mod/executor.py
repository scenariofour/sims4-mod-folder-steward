from __future__ import annotations

import os
from collections.abc import Callable, Collection
from datetime import UTC, datetime
from pathlib import Path

from .hashing import sha256_file
from .models import (
    ManifestOperation,
    ManifestStatus,
    OperationStatus,
    PlanAction,
    RunManifest,
    RunPlan,
    ScanSnapshot,
)
from .paths import (
    WorkspacePaths,
    ensure_no_symlink_components,
    is_within,
    safe_join,
    validate_run_directory,
)
from .quarantine import duplicate_quarantine_relative, replacement_quarantine_relative
from .scanner import scan_mods
from .storage import json_compatible, read_json_object, write_json_atomic, write_json_new

BeforeOperation = Callable[[ManifestOperation], None]


class ExecutionError(RuntimeError):
    """Raised when a plan cannot be safely applied."""


def prepare_run_documents(
    run_directory: Path,
    before: ScanSnapshot,
    plan: RunPlan,
) -> None:
    if before.run_id != plan.run_id:
        raise ExecutionError("Snapshot and plan run IDs do not match.")
    write_json_new(run_directory / "before.json", before.to_dict())
    write_json_new(run_directory / "plan.json", plan.to_dict())


def _error_text(error: BaseException) -> str:
    return str(error) or error.__class__.__name__


def _assert_regular_file(path: Path, *, label: str) -> None:
    if not path.exists():
        raise ExecutionError(f"{label} does not exist: {path}")
    if path.is_symlink() or not path.is_file():
        raise ExecutionError(f"{label} must be a regular, non-symlink file: {path}")


def _resolved_paths(
    operation: ManifestOperation,
    run_directory: Path,
    workspace: WorkspacePaths,
) -> tuple[Path, Path, Path | None]:
    if operation.action == PlanAction.BACKUP:
        source = safe_join(workspace.mods_root, operation.source)
    else:
        source = safe_join(run_directory, operation.source)
        staging_root = run_directory / "staging"
        if not is_within(source, staging_root, allow_equal=False):
            raise ExecutionError("Operation source must be inside this run's staging directory.")
    destination = safe_join(workspace.mods_root, operation.destination)
    if destination.name.casefold() == "resource.cfg" and destination.parent == workspace.mods_root:
        raise ExecutionError("resource.cfg is protected and cannot be an operation target.")
    quarantine = (
        safe_join(run_directory, operation.quarantine_path)
        if operation.quarantine_path is not None
        else None
    )
    return source, destination, quarantine


def _preflight_operation(
    operation: ManifestOperation,
    run_directory: Path,
    workspace: WorkspacePaths,
) -> None:
    source, destination, quarantine = _resolved_paths(operation, run_directory, workspace)
    source_root = workspace.mods_root if operation.action == PlanAction.BACKUP else run_directory
    ensure_no_symlink_components(source, source_root)
    ensure_no_symlink_components(destination.parent, workspace.mods_root)
    _assert_regular_file(
        source,
        label="Duplicate source" if operation.action == PlanAction.BACKUP else "Staged source",
    )
    if sha256_file(source) != operation.source_sha256:
        raise ExecutionError(f"Operation source hash changed: {operation.source}")

    if operation.action == PlanAction.BACKUP:
        if source != destination or quarantine is None:
            raise ExecutionError("Duplicate backup paths are inconsistent.")
        ensure_no_symlink_components(quarantine.parent, run_directory)
        if quarantine.exists() or quarantine.is_symlink():
            raise ExecutionError(f"Backup destination already exists: {operation.quarantine_path}")
        return

    if operation.action == PlanAction.INSTALL:
        if destination.exists() or destination.is_symlink():
            raise ExecutionError(f"Install destination already exists: {operation.destination}")
        return
    if operation.action != PlanAction.REPLACE or quarantine is None:
        raise ExecutionError(f"Unsupported executable action: {operation.action}")
    _assert_regular_file(destination, label="Replacement target")
    if operation.target_before_sha256 is None:
        raise ExecutionError("Replacement target hash is missing.")
    if sha256_file(destination) != operation.target_before_sha256:
        raise ExecutionError(f"Replacement target hash changed: {operation.destination}")
    ensure_no_symlink_components(quarantine.parent, run_directory)
    if quarantine.exists() or quarantine.is_symlink():
        raise ExecutionError(f"Quarantine destination already exists: {operation.quarantine_path}")


def _apply_operation(
    operation: ManifestOperation,
    run_directory: Path,
    workspace: WorkspacePaths,
) -> None:
    source, destination, quarantine = _resolved_paths(operation, run_directory, workspace)
    if operation.action == PlanAction.BACKUP:
        assert quarantine is not None
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, quarantine)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if operation.action == PlanAction.INSTALL:
        moved = False
        try:
            os.replace(source, destination)
            moved = True
            if sha256_file(destination) != operation.source_sha256:
                raise ExecutionError(f"Installed file verification failed: {operation.destination}")
        except BaseException:
            if moved and destination.exists():
                os.replace(destination, source)
            raise
        return

    assert quarantine is not None
    quarantine.parent.mkdir(parents=True, exist_ok=True)
    old_moved = False
    new_moved = False
    try:
        os.replace(destination, quarantine)
        old_moved = True
        os.replace(source, destination)
        new_moved = True
        if sha256_file(destination) != operation.source_sha256:
            raise ExecutionError(f"Replacement verification failed: {operation.destination}")
    except BaseException:
        if new_moved and destination.exists():
            os.replace(destination, source)
        if old_moved and quarantine.exists():
            os.replace(quarantine, destination)
        raise


def _rollback_operation(
    operation: ManifestOperation,
    run_directory: Path,
    workspace: WorkspacePaths,
) -> None:
    source, destination, quarantine = _resolved_paths(operation, run_directory, workspace)
    if operation.action == PlanAction.BACKUP:
        if quarantine is None:
            raise ExecutionError("Duplicate backup rollback data is incomplete.")
        if destination.exists() or destination.is_symlink():
            raise ExecutionError(f"Duplicate path is occupied: {operation.destination}")
        _assert_regular_file(quarantine, label="Backed-up duplicate")
        if sha256_file(quarantine) != operation.source_sha256:
            raise ExecutionError(f"Backed-up duplicate changed: {operation.quarantine_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(quarantine, destination)
        return
    source.parent.mkdir(parents=True, exist_ok=True)
    if source.exists() or source.is_symlink():
        raise ExecutionError(f"Rollback source path is occupied: {operation.source}")
    _assert_regular_file(destination, label="Applied destination")
    if sha256_file(destination) != operation.source_sha256:
        raise ExecutionError(f"Applied file changed before rollback: {operation.destination}")
    if operation.action == PlanAction.INSTALL:
        os.replace(destination, source)
        return
    if quarantine is None or operation.target_before_sha256 is None:
        raise ExecutionError("Replacement rollback data is incomplete.")
    _assert_regular_file(quarantine, label="Quarantined original")
    if sha256_file(quarantine) != operation.target_before_sha256:
        raise ExecutionError(f"Quarantined file changed: {operation.quarantine_path}")
    os.replace(destination, source)
    try:
        os.replace(quarantine, destination)
    except BaseException:
        os.replace(source, destination)
        raise


def _manifest_operations(
    plan: RunPlan,
    approved_operation_ids: Collection[str],
) -> list[ManifestOperation]:
    executable = {
        operation.operation_id: operation
        for operation in plan.operations
        if operation.action in {PlanAction.INSTALL, PlanAction.REPLACE, PlanAction.BACKUP}
    }
    unknown_approvals = set(approved_operation_ids) - set(executable)
    if unknown_approvals:
        raise ExecutionError("Approval contains an unknown or non-executable operation ID.")

    result: list[ManifestOperation] = []
    for operation in executable.values():
        if operation.destination is None or operation.source_sha256 is None:
            raise ExecutionError("Executable plan operation is missing required fields.")
        approved = not operation.requires_review or operation.operation_id in approved_operation_ids
        if operation.action == PlanAction.REPLACE:
            quarantine_path = replacement_quarantine_relative(operation)
        elif operation.action == PlanAction.BACKUP:
            quarantine_path = duplicate_quarantine_relative(operation)
        else:
            quarantine_path = None
        result.append(
            ManifestOperation(
                operation_id=operation.operation_id,
                action=operation.action,
                source=operation.source,
                destination=operation.destination,
                status=OperationStatus.PENDING if approved else OperationStatus.SKIPPED,
                source_sha256=operation.source_sha256,
                target_before_sha256=operation.target_sha256,
                quarantine_path=quarantine_path,
            )
        )
    return result


def apply_plan(
    plan: RunPlan,
    workspace: WorkspacePaths,
    run_directory: Path,
    before: ScanSnapshot,
    *,
    approved_operation_ids: Collection[str] = (),
    before_operation: BeforeOperation | None = None,
) -> RunManifest:
    run_directory = validate_run_directory(run_directory, workspace, must_exist=True)
    if before.run_id != plan.run_id:
        raise ExecutionError("Snapshot and plan run IDs do not match.")
    if read_json_object(run_directory / "before.json") != json_compatible(before.to_dict()):
        raise ExecutionError("before.json does not match the supplied snapshot.")
    if read_json_object(run_directory / "plan.json") != json_compatible(plan.to_dict()):
        raise ExecutionError("plan.json does not match the supplied plan.")
    manifest_path = run_directory / "manifest.json"
    if manifest_path.exists():
        raise ExecutionError("This run already has a manifest and cannot be applied again.")

    operations = _manifest_operations(plan, approved_operation_ids)
    pending = [item for item in operations if item.status == OperationStatus.PENDING]
    seen_destinations: set[str] = set()
    for operation in pending:
        destination_key = operation.destination.casefold()
        if destination_key in seen_destinations:
            raise ExecutionError(f"Plan contains duplicate destination: {operation.destination}")
        seen_destinations.add(destination_key)
        _preflight_operation(operation, run_directory, workspace)

    manifest = RunManifest(
        run_id=plan.run_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        status=ManifestStatus.APPLYING,
        operations=operations,
    )
    write_json_atomic(manifest_path, manifest.to_dict())

    current: ManifestOperation | None = None
    try:
        for current in pending:
            if before_operation is not None:
                before_operation(current)
            _apply_operation(current, run_directory, workspace)
            current.status = OperationStatus.COMPLETED
            write_json_atomic(manifest_path, manifest.to_dict())

        after = scan_mods(workspace.mods_root, language=before.language)
        write_json_atomic(run_directory / "after.json", after.to_dict())
        manifest.after_snapshot = "after.json"
        manifest.status = ManifestStatus.APPLIED
        write_json_atomic(manifest_path, manifest.to_dict())
        return manifest
    except (Exception, KeyboardInterrupt) as error:
        if current is not None and current.status == OperationStatus.PENDING:
            current.status = OperationStatus.FAILED
            current.error = _error_text(error)
        rollback_error: BaseException | None = None
        for completed in reversed(operations):
            if completed.status != OperationStatus.COMPLETED:
                continue
            try:
                _rollback_operation(completed, run_directory, workspace)
                completed.status = OperationStatus.ROLLED_BACK
            except (Exception, KeyboardInterrupt) as candidate:  # noqa: BLE001
                completed.error = _error_text(candidate)
                rollback_error = candidate
                break
            finally:
                write_json_atomic(manifest_path, manifest.to_dict())
        manifest.status = (
            ManifestStatus.ROLLBACK_FAILED
            if rollback_error is not None
            else ManifestStatus.ROLLED_BACK
        )
        write_json_atomic(manifest_path, manifest.to_dict())
        detail = _error_text(error)
        if rollback_error is not None:
            detail += f"; rollback also failed: {_error_text(rollback_error)}"
        raise ExecutionError(f"Apply failed: {detail}") from error
