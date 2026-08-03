from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from s4mod.archives import stage_inbox
from s4mod.executor import ExecutionError, apply_plan, prepare_run_documents
from s4mod.models import ManifestStatus, OperationStatus, PlanAction
from s4mod.paths import build_workspace_paths
from s4mod.planner import build_plan
from s4mod.rollback import UndoError, undo_run
from s4mod.scanner import scan_mods


def _planned_run(
    tmp_path: Path,
    inbox_files: dict[str, bytes],
    mods_files: dict[str, bytes] | None = None,
) -> tuple[Path, Path, object, object, object]:
    workspace_root = tmp_path / "The Sims 4"
    mods = workspace_root / "Mods"
    inbox = workspace_root / "Inbox"
    run = workspace_root / "S4ModSteward" / "runs" / "run-test"
    mods.mkdir(parents=True)
    inbox.mkdir()
    run.mkdir(parents=True)
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    for relative, content in (mods_files or {}).items():
        target = mods / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for relative, content in inbox_files.items():
        target = inbox / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    before = scan_mods(mods, run_id="run-test")
    stage = stage_inbox(inbox, run / "staging")
    plan = build_plan(before, stage, run_id="run-test")
    prepare_run_documents(run, before, plan)
    return mods, run, build_workspace_paths(mods), before, plan


def test_apply_install_writes_manifest_and_after_snapshot(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(
        tmp_path,
        {"Creator/New.package": b"new"},
    )

    manifest = apply_plan(plan, workspace, run, before)

    assert manifest.status == ManifestStatus.APPLIED
    assert (mods / "Creator" / "New.package").read_bytes() == b"new"
    assert (run / "after.json").is_file()
    assert manifest.operations[0].status == OperationStatus.COMPLETED


def test_apply_replace_quarantines_original(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(
        tmp_path,
        {"Replace.package": b"new"},
        {"Replace.package": b"old"},
    )
    replacement = next(item for item in plan.operations if item.action == PlanAction.REPLACE)

    manifest = apply_plan(
        plan,
        workspace,
        run,
        before,
        approved_operation_ids={replacement.operation_id},
    )

    operation = manifest.operations[0]
    assert (mods / "Replace.package").read_bytes() == b"new"
    assert operation.quarantine_path is not None
    assert (run / operation.quarantine_path).read_bytes() == b"old"


def test_unapproved_reviewed_replace_is_skipped(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(
        tmp_path,
        {"Replace.package": b"new"},
        {"Replace.package": b"old"},
    )

    manifest = apply_plan(plan, workspace, run, before)

    assert manifest.operations[0].status == OperationStatus.SKIPPED
    assert (mods / "Replace.package").read_bytes() == b"old"


def test_failed_replacement_move_immediately_restores_original(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mods, run, workspace, before, plan = _planned_run(
        tmp_path,
        {"Replace.package": b"new"},
        {"Replace.package": b"old"},
    )
    replacement = next(item for item in plan.operations if item.action == PlanAction.REPLACE)
    real_replace = os.replace
    failed = False

    def fail_new_file(source: Path, destination: Path) -> None:
        nonlocal failed
        if not failed and "staging" in source.parts and destination == mods / "Replace.package":
            failed = True
            raise PermissionError("synthetic replacement move failure")
        real_replace(source, destination)

    monkeypatch.setattr("s4mod.executor.os.replace", fail_new_file)
    with pytest.raises(ExecutionError, match="synthetic replacement move failure"):
        apply_plan(
            plan,
            workspace,
            run,
            before,
            approved_operation_ids={replacement.operation_id},
        )

    assert (mods / "Replace.package").read_bytes() == b"old"
    assert (run / "staging" / "direct" / "Replace.package").read_bytes() == b"new"


def test_preflight_failure_makes_no_changes_and_no_manifest(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(tmp_path, {"New.package": b"new"})
    (mods / "New.package").write_bytes(b"unexpected")

    with pytest.raises(ExecutionError, match="already exists"):
        apply_plan(plan, workspace, run, before)

    assert (mods / "New.package").read_bytes() == b"unexpected"
    assert (run / "staging" / "direct" / "New.package").is_file()
    assert not (run / "manifest.json").exists()


def test_preflight_refuses_changed_staged_source(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(tmp_path, {"New.package": b"new"})
    staged = run / "staging" / "direct" / "New.package"
    staged.write_bytes(b"changed after planning")

    with pytest.raises(ExecutionError, match="source hash changed"):
        apply_plan(plan, workspace, run, before)

    assert not (mods / "New.package").exists()
    assert not (run / "manifest.json").exists()


def test_failure_after_first_operation_rolls_back_completed_work(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(
        tmp_path,
        {"A.package": b"a", "B.package": b"b"},
    )
    calls = 0

    def fail_second(_operation: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("synthetic permission failure")

    with pytest.raises(ExecutionError, match="synthetic permission failure"):
        apply_plan(plan, workspace, run, before, before_operation=fail_second)

    assert not (mods / "A.package").exists()
    assert not (mods / "B.package").exists()
    assert (run / "staging" / "direct" / "A.package").is_file()
    assert (run / "staging" / "direct" / "B.package").is_file()
    document = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert document["status"] == "rolled_back"


def test_keyboard_interrupt_is_recorded_and_rolled_back(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(tmp_path, {"New.package": b"new"})

    def interrupt(_operation: object) -> None:
        raise KeyboardInterrupt

    with pytest.raises(ExecutionError, match="KeyboardInterrupt"):
        apply_plan(plan, workspace, run, before, before_operation=interrupt)

    assert not (mods / "New.package").exists()
    document = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert document["status"] == "rolled_back"


def test_undo_restores_install_and_replacement(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(
        tmp_path,
        {"New.package": b"new", "Replace.package": b"replacement"},
        {"Replace.package": b"original"},
    )
    replacement = next(item for item in plan.operations if item.action == PlanAction.REPLACE)
    apply_plan(
        plan,
        workspace,
        run,
        before,
        approved_operation_ids={replacement.operation_id},
    )

    manifest = undo_run(run, workspace)

    assert manifest.status == ManifestStatus.ROLLED_BACK
    assert not (mods / "New.package").exists()
    assert (mods / "Replace.package").read_bytes() == b"original"
    assert (run / "staging" / "direct" / "New.package").read_bytes() == b"new"
    assert (run / "staging" / "direct" / "Replace.package").read_bytes() == b"replacement"
    with pytest.raises(UndoError, match="Only an applied run"):
        undo_run(run, workspace)


def test_undo_preflight_refuses_changed_destination(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(tmp_path, {"New.package": b"new"})
    apply_plan(plan, workspace, run, before)
    (mods / "New.package").write_bytes(b"user changed it")

    with pytest.raises(UndoError, match="hash changed"):
        undo_run(run, workspace)

    assert (mods / "New.package").read_bytes() == b"user changed it"


def test_undo_preflight_refuses_occupied_staging_path(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(tmp_path, {"New.package": b"new"})
    apply_plan(plan, workspace, run, before)
    staged = run / "staging" / "direct" / "New.package"
    staged.write_bytes(b"occupied")

    with pytest.raises(UndoError, match="occupied"):
        undo_run(run, workspace)

    assert (mods / "New.package").read_bytes() == b"new"
    assert staged.read_bytes() == b"occupied"


def test_partial_undo_failure_recovers_applied_files(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(
        tmp_path,
        {"A.package": b"a", "B.package": b"b"},
    )
    apply_plan(plan, workspace, run, before)
    calls = 0

    def fail_second(_operation: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("synthetic undo failure")

    with pytest.raises(UndoError, match="synthetic undo failure"):
        undo_run(run, workspace, before_operation=fail_second)

    assert (mods / "A.package").read_bytes() == b"a"
    assert (mods / "B.package").read_bytes() == b"b"
    document = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert document["status"] == "rollback_failed"


def test_duplicate_backup_is_applied_and_undo_restores_it(tmp_path: Path) -> None:
    mods, run, workspace, before, plan = _planned_run(
        tmp_path,
        {},
        {"Keep.package": b"same", "Creator/Copy.package": b"same"},
    )

    manifest = apply_plan(plan, workspace, run, before)

    backup = next(
        operation for operation in manifest.operations if operation.action == PlanAction.BACKUP
    )
    assert not (mods / "Creator" / "Copy.package").exists()
    assert (mods / "Keep.package").is_file()
    assert backup.quarantine_path is not None
    assert (run / backup.quarantine_path).read_bytes() == b"same"

    undo_run(run, workspace)
    assert (mods / "Creator" / "Copy.package").read_bytes() == b"same"
