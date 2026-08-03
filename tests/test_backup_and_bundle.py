from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from s4mod.ai_bundle import AI_FILES, ai_review_prompt, export_ai_check_bundle
from s4mod.backup import BackupError, create_full_mods_backup, estimate_backup_bytes
from s4mod.localization import Translator
from s4mod.paths import build_workspace_paths
from s4mod.privacy import PathRedactor
from s4mod.reports import write_scan_reports
from s4mod.scanner import scan_mods


def _run(tmp_path: Path) -> tuple[Path, Path, object, object]:
    root = tmp_path / "The Sims 4"
    mods = root / "Mods"
    run = root / "S4ModSteward" / "runs" / "run-test"
    mods.mkdir(parents=True)
    run.mkdir(parents=True)
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    (mods / "Creator").mkdir()
    (mods / "Creator" / "Fictional.package").write_bytes(b"synthetic fixture")
    (mods / "Empty Folder").mkdir()
    workspace = build_workspace_paths(mods)
    snapshot = scan_mods(mods, run_id="run-test")
    return mods, run, workspace, snapshot


def test_complete_backup_copies_all_files_without_changing_mods(tmp_path: Path) -> None:
    mods, run, workspace, snapshot = _run(tmp_path)

    summary = create_full_mods_backup(workspace, run, snapshot)

    assert summary.bytes == estimate_backup_bytes(snapshot)
    assert summary.files == 2
    assert (run / "full-mods-backup" / "resource.cfg").is_file()
    assert (run / "full-mods-backup" / "Empty Folder").is_dir()
    assert (
        run / "full-mods-backup" / "Creator" / "Fictional.package"
    ).read_bytes() == b"synthetic fixture"
    assert (mods / "Creator" / "Fictional.package").is_file()


def test_complete_backup_refuses_mods_changed_after_scan(tmp_path: Path) -> None:
    mods, run, workspace, snapshot = _run(tmp_path)
    (mods / "New.package").write_bytes(b"new after scan")

    with pytest.raises(BackupError, match="changed after the scan"):
        create_full_mods_backup(workspace, run, snapshot)

    assert not (run / "full-mods-backup").exists()


def test_ai_bundle_contains_only_anonymized_reports_and_prompt(tmp_path: Path) -> None:
    mods, run, workspace, snapshot = _run(tmp_path)
    translator = Translator.load("zh-CN")
    redactor = PathRedactor.for_run(
        mods_root=mods,
        workspace_root=workspace.workspace_root,
        run_root=run,
    )
    write_scan_reports(snapshot, run, translator=translator, redactor=redactor)
    destination = tmp_path / "AI_CHECK.zip"

    exported = export_ai_check_bundle(run, destination, language="zh-CN")

    with zipfile.ZipFile(exported) as bundle:
        assert set(bundle.namelist()) == {*AI_FILES, "AI_PROMPT.txt"}
        contents = b"\n".join(bundle.read(name) for name in bundle.namelist())
    assert str(tmp_path).encode() not in contents
    assert b"synthetic fixture" not in contents
    assert "浏览工具" in ai_review_prompt("zh-CN")
