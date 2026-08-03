from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .archives import ArchiveSafetyError, stage_inbox
from .executor import prepare_run_documents
from .localization import Translator
from .models import InboxNotice, InboxStage, RunPlan, ScanSnapshot, StagedCandidate
from .paths import WorkspacePaths, ensure_no_symlink_components, validate_run_directory
from .planner import build_plan, render_plan_text
from .privacy import PathRedactor
from .reports import write_scan_reports
from .scanner import scan_mods

DROP_EXTENSIONS = frozenset({".zip", ".package", ".ts4script"})


@dataclass(frozen=True, slots=True)
class RunSession:
    run_directory: Path
    workspace: WorkspacePaths
    before: ScanSnapshot
    plan: RunPlan


def _combine_stages(stages: list[InboxStage]) -> InboxStage:
    candidates: list[StagedCandidate] = []
    notices: list[InboxNotice] = []
    for stage in stages:
        candidates.extend(stage.candidates)
        notices.extend(stage.notices)
    candidates.sort(key=lambda item: (item.proposed_path.casefold(), item.source))
    notices.sort(key=lambda item: (item.source.casefold(), item.code))
    return InboxStage(candidates=tuple(candidates), notices=tuple(notices))


def _stage_sources(
    run_directory: Path,
    inbox_roots: tuple[Path, ...],
    dropped_files: tuple[Path, ...],
) -> InboxStage:
    stages: list[InboxStage] = []
    staging_root = run_directory / "staging"
    staging_root.mkdir()

    for index, inbox in enumerate(inbox_roots, start=1):
        if any(part.casefold() == "saves" for part in inbox.parts):
            raise ArchiveSafetyError("Saves cannot be used as an Inbox source.")
        stages.append(
            stage_inbox(
                inbox,
                staging_root / f"inbox-{index:03d}",
                source_base=run_directory,
            )
        )

    for index, dropped in enumerate(dropped_files, start=1):
        if any(part.casefold() == "saves" for part in dropped.parts):
            raise ArchiveSafetyError("Files inside Saves cannot be staged.")
        if dropped.is_symlink() or not dropped.is_file():
            raise ArchiveSafetyError(f"Dropped item is not a regular file: {dropped.name}")
        if dropped.suffix.casefold() not in DROP_EXTENSIONS:
            raise ArchiveSafetyError(f"Unsupported dropped file: {dropped.name}")
        intake = run_directory / "intake" / f"drop-{index:03d}"
        intake.mkdir(parents=True)
        copied = intake / dropped.name
        shutil.copy2(dropped, copied)
        stages.append(
            stage_inbox(
                intake,
                staging_root / f"drop-{index:03d}",
                source_base=run_directory,
            )
        )
    return _combine_stages(stages)


def create_plan_run(
    workspace: WorkspacePaths,
    *,
    language: str,
    profile_name: str,
    inbox_roots: tuple[Path, ...] = (),
    dropped_files: tuple[Path, ...] = (),
) -> RunSession:
    translator = Translator.load(language)
    ensure_no_symlink_components(workspace.state_root, workspace.workspace_root)
    workspace.state_root.mkdir(exist_ok=True)
    before = scan_mods(workspace.mods_root, language=translator.language)
    run_directory = validate_run_directory(
        workspace.state_root / "runs" / before.run_id,
        workspace,
        must_exist=False,
    )
    run_directory.parent.mkdir(parents=True, exist_ok=True)
    run_directory.mkdir()
    stage = _stage_sources(run_directory, inbox_roots, dropped_files)
    plan = build_plan(
        before,
        stage,
        profile_name=profile_name,
        run_id=before.run_id,
    )
    prepare_run_documents(run_directory, before, plan)
    (run_directory / "plan.txt").write_text(
        render_plan_text(plan, translator),
        encoding="utf-8",
        newline="\n",
    )
    redactor = PathRedactor.for_run(
        mods_root=workspace.mods_root,
        workspace_root=workspace.workspace_root,
        run_root=run_directory,
    )
    write_scan_reports(before, run_directory, translator=translator, redactor=redactor)
    return RunSession(
        run_directory=run_directory,
        workspace=workspace,
        before=before,
        plan=plan,
    )
