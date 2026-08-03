from __future__ import annotations

from pathlib import Path

import pytest

from s4mod.archives import ArchiveSafetyError
from s4mod.models import PlanAction
from s4mod.paths import build_workspace_paths
from s4mod.workflow import create_plan_run


def test_workflow_accepts_selected_inbox_and_dropped_files(tmp_path: Path) -> None:
    root = tmp_path / "The Sims 4"
    mods = root / "Mods"
    inbox = tmp_path / "Downloads" / "Inbox"
    dropped = tmp_path / "Downloads" / "Dropped.package"
    mods.mkdir(parents=True)
    inbox.mkdir(parents=True)
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    (inbox / "Inbox.package").write_bytes(b"from inbox")
    dropped.write_bytes(b"dropped")

    session = create_plan_run(
        build_workspace_paths(mods),
        language="en",
        profile_name="neutral",
        inbox_roots=(inbox,),
        dropped_files=(dropped,),
    )

    installs = [item for item in session.plan.operations if item.action == PlanAction.INSTALL]
    assert {item.destination for item in installs} == {"Inbox.package", "Dropped.package"}
    assert all(item.source.startswith("staging/") for item in installs)
    assert (session.run_directory / "report.html").is_file()
    assert (session.run_directory / "AI_HANDOFF.md").is_file()


def test_workflow_refuses_any_input_inside_saves(tmp_path: Path) -> None:
    root = tmp_path / "The Sims 4"
    mods = root / "Mods"
    forbidden = root / "Saves" / "Inbox"
    mods.mkdir(parents=True)
    forbidden.mkdir(parents=True)
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")

    with pytest.raises(ArchiveSafetyError, match="Saves"):
        create_plan_run(
            build_workspace_paths(mods),
            language="en",
            profile_name="neutral",
            inbox_roots=(forbidden,),
        )
