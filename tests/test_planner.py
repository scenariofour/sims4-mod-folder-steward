from __future__ import annotations

import zipfile
from pathlib import Path

from s4mod.archives import stage_inbox
from s4mod.models import PlanAction
from s4mod.planner import build_plan
from s4mod.scanner import scan_mods


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    mods = tmp_path / "The Sims 4" / "Mods"
    inbox = tmp_path / "The Sims 4" / "Inbox"
    run = tmp_path / "The Sims 4" / "S4ModSteward" / "runs" / "run-test"
    mods.mkdir(parents=True)
    inbox.mkdir()
    run.mkdir(parents=True)
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    return mods, inbox, run


def test_plan_classifies_install_skip_replace_conflict_and_non_mod(tmp_path: Path) -> None:
    mods, inbox, run = _roots(tmp_path)
    (mods / "Installed.package").write_bytes(b"same")
    (mods / "Replace.package").write_bytes(b"old")
    (mods / "Elsewhere").mkdir()
    (mods / "Elsewhere" / "Conflict.package").write_bytes(b"old conflict")
    (inbox / "New.package").write_bytes(b"new")
    (inbox / "Installed.package").write_bytes(b"same")
    (inbox / "Replace.package").write_bytes(b"new replacement")
    (inbox / "Conflict.package").write_bytes(b"new conflict")
    (inbox / "notes.txt").write_text("notes", encoding="utf-8")

    stage = stage_inbox(inbox, run / "staging")
    plan = build_plan(scan_mods(mods, run_id="run-test"), stage, run_id="run-test")
    by_reason = {operation.reason: operation for operation in plan.operations}

    assert by_reason["new_file"].action == PlanAction.INSTALL
    assert by_reason["exact_file_already_installed"].action == PlanAction.SKIP
    assert by_reason["same_relative_path_different_content"].action == PlanAction.REPLACE
    assert by_reason["same_relative_path_different_content"].requires_review
    assert by_reason["same_name_different_content"].action == PlanAction.REVIEW
    assert by_reason["non_mod_file"].action == PlanAction.REVIEW


def test_plan_requires_review_for_inbox_collision_and_deep_script(tmp_path: Path) -> None:
    mods, inbox, run = _roots(tmp_path)
    with zipfile.ZipFile(inbox / "one.zip", "w") as archive:
        archive.writestr("same.package", b"one")
    with zipfile.ZipFile(inbox / "two.zip", "w") as archive:
        archive.writestr("same.package", b"two")
    deep = inbox / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "script.ts4script").write_bytes(b"script")

    stage = stage_inbox(inbox, run / "staging")
    plan = build_plan(scan_mods(mods, run_id="run-test"), stage, run_id="run-test")

    conflicts = [
        operation
        for operation in plan.operations
        if operation.reason == "inbox_destination_conflict"
    ]
    assert len(conflicts) == 2
    assert all(operation.action == PlanAction.REVIEW for operation in conflicts)
    assert any(operation.reason == "script_destination_too_deep" for operation in plan.operations)
    assert all(
        operation.action == PlanAction.REVIEW
        for operation in plan.operations
        if operation.reason == "script_destination_too_deep"
    )


def test_localized_profile_routes_unclassified_files_to_review(tmp_path: Path) -> None:
    mods, inbox, run = _roots(tmp_path)
    (inbox / "New.package").write_bytes(b"new")
    stage = stage_inbox(inbox, run / "staging")

    plan = build_plan(
        scan_mods(mods, run_id="run-test"),
        stage,
        profile_name="zh-CN",
        run_id="run-test",
    )

    operation = plan.operations[0]
    assert operation.action == PlanAction.INSTALL
    assert operation.requires_review
    assert operation.destination is not None
    assert operation.destination.startswith("99_人工检查/")


def test_exact_duplicate_in_mods_is_planned_for_reversible_backup(tmp_path: Path) -> None:
    mods, inbox, run = _roots(tmp_path)
    (mods / "Keep.package").write_bytes(b"same")
    duplicate_folder = mods / "Creator"
    duplicate_folder.mkdir()
    (duplicate_folder / "Copy.package").write_bytes(b"same")

    stage = stage_inbox(inbox, run / "staging")
    plan = build_plan(scan_mods(mods, run_id="run-test"), stage, run_id="run-test")

    backup = next(
        operation for operation in plan.operations if operation.action == PlanAction.BACKUP
    )
    assert backup.source == "Creator/Copy.package"
    assert backup.destination == "Creator/Copy.package"
    assert not backup.requires_review
    assert backup.evidence["matching_file_kept"] == "Keep.package"
