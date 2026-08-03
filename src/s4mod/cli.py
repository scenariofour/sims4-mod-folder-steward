from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .archives import ArchiveSafetyError
from .executor import ExecutionError, apply_plan
from .localization import SUPPORTED_LOCALES, Translator
from .models import ManifestStatus, PlanAction, RunPlan, ScanSnapshot
from .paths import (
    PathSafetyError,
    WorkspacePaths,
    build_workspace_paths,
    discover_mods_path,
    ensure_no_symlink_components,
    validate_inbox_directory,
    validate_report_directory,
    validate_run_directory,
)
from .planner import render_plan_text
from .privacy import PathRedactor
from .reports import write_scan_reports
from .rollback import UndoError, load_manifest, undo_run
from .scanner import scan_mods
from .workflow import create_plan_run

FOLDER_PROFILES = ("neutral", "en", "zh-CN")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="s4mod",
        description="Local-first Sims 4 Mods folder steward.",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command")
    scan_parser = subparsers.add_parser("scan", help="Read-only scan and report.")
    _add_mods_and_language(scan_parser)
    scan_parser.add_argument(
        "--output",
        type=Path,
        help="New report directory inside the selected Sims 4 workspace.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Stage an Inbox and create a plan; apply only with explicit confirmation.",
    )
    _add_mods_and_language(run_parser)
    run_parser.add_argument("--inbox", type=Path, help="Optional Inbox inside the workspace.")
    run_parser.add_argument(
        "--profile",
        choices=FOLDER_PROFILES,
        default="neutral",
        help="Category folder language; neutral preserves proposed structure.",
    )
    run_parser.add_argument(
        "--apply",
        action="store_true",
        help="Interactively approve reviewed operations and apply the plan.",
    )

    undo_parser = subparsers.add_parser("undo", help="Undo a previously applied run.")
    _add_mods_and_language(undo_parser)
    undo_parser.add_argument("--run", type=Path, required=True, help="Applied run directory.")
    return parser


def _add_mods_and_language(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mods", type=Path, help="Path to the Sims 4 Mods folder.")
    parser.add_argument(
        "--lang",
        choices=SUPPORTED_LOCALES,
        default="en",
        help="Interface and report language.",
    )


def _run_scan(args: argparse.Namespace) -> int:
    translator = Translator.load(args.lang)
    mods_root = discover_mods_path(args.mods)
    workspace = build_workspace_paths(mods_root)
    snapshot = scan_mods(mods_root, language=translator.language)

    if args.output is None:
        requested_output = workspace.state_root / "runs" / snapshot.run_id
    elif args.output.is_absolute():
        requested_output = args.output
    else:
        requested_output = workspace.workspace_root / args.output
    output_directory = validate_report_directory(requested_output, workspace)
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    output_directory.mkdir(exist_ok=False)

    redactor = PathRedactor.for_run(
        mods_root=workspace.mods_root,
        workspace_root=workspace.workspace_root,
        run_root=output_directory,
    )
    written = write_scan_reports(
        snapshot,
        output_directory,
        translator=translator,
        redactor=redactor,
    )
    print(translator.text("cli.scan_complete"))
    print(translator.text("cli.files_scanned", count=snapshot.summary.files_total))
    print(translator.text("cli.findings_found", count=len(snapshot.findings)))
    print(translator.text("cli.reports_written", path=output_directory))
    for filename in written:
        print(f"  - {filename}")
    return 0


def _create_run(
    args: argparse.Namespace,
) -> tuple[Path, WorkspacePaths, ScanSnapshot, RunPlan, Translator]:
    translator = Translator.load(args.lang)
    mods_root = discover_mods_path(args.mods)
    workspace = build_workspace_paths(mods_root)
    ensure_no_symlink_components(workspace.state_root, workspace.workspace_root)
    workspace.state_root.mkdir(exist_ok=True)

    if args.inbox is None:
        inbox = workspace.state_root / "Inbox"
        inbox.mkdir(exist_ok=True)
    else:
        inbox = args.inbox if args.inbox.is_absolute() else workspace.workspace_root / args.inbox
    inbox = validate_inbox_directory(inbox, workspace)

    session = create_plan_run(
        workspace,
        language=translator.language,
        profile_name=args.profile,
        inbox_roots=(inbox,),
    )
    return session.run_directory, workspace, session.before, session.plan, translator


def _run_plan(args: argparse.Namespace) -> int:
    run_directory, workspace, snapshot, plan, translator = _create_run(args)
    print(render_plan_text(plan, translator), end="")
    print(translator.text("cli.plan_written", path=run_directory))
    if not args.apply:
        print(translator.text("cli.dry_run_complete"))
        return 0

    approved: set[str] = set()
    for operation in plan.operations:
        if operation.action not in {PlanAction.INSTALL, PlanAction.REPLACE}:
            continue
        if not operation.requires_review:
            continue
        expected = f"APPROVE {operation.operation_id}"
        response = input(translator.text("cli.approve_operation", phrase=expected) + " ")
        if response == expected:
            approved.add(operation.operation_id)

    expected_apply = f"APPLY {plan.run_id}"
    response = input(translator.text("cli.apply_confirmation", phrase=expected_apply) + " ")
    if response != expected_apply:
        print(translator.text("cli.apply_cancelled"))
        return 0
    manifest = apply_plan(
        plan,
        workspace,
        run_directory,
        snapshot,
        approved_operation_ids=approved,
    )
    completed = sum(operation.status.value == "completed" for operation in manifest.operations)
    print(translator.text("cli.apply_complete", count=completed))
    return 0


def _run_undo(args: argparse.Namespace) -> int:
    translator = Translator.load(args.lang)
    mods_root = discover_mods_path(args.mods)
    workspace = build_workspace_paths(mods_root)
    requested = args.run if args.run.is_absolute() else workspace.workspace_root / args.run
    run_directory = validate_run_directory(requested, workspace, must_exist=True)
    manifest = load_manifest(run_directory, workspace)
    if manifest.status != ManifestStatus.APPLIED:
        raise UndoError(f"Run is not applied (status: {manifest.status}).")
    expected = f"UNDO {manifest.run_id}"
    response = input(translator.text("cli.undo_confirmation", phrase=expected) + " ")
    if response != expected:
        print(translator.text("cli.undo_cancelled"))
        return 0
    undone = undo_run(run_directory, workspace)
    count = sum(operation.status.value == "rolled_back" for operation in undone.operations)
    print(translator.text("cli.undo_complete", count=count))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "scan":
            return _run_scan(args)
        if args.command == "run":
            return _run_plan(args)
        if args.command == "undo":
            return _run_undo(args)
    except (
        ArchiveSafetyError,
        ExecutionError,
        FileExistsError,
        FileNotFoundError,
        NotADirectoryError,
        PathSafetyError,
        UndoError,
        ValueError,
    ) as error:
        print(f"s4mod: {error}", file=sys.stderr)
        return 2
    return 2
