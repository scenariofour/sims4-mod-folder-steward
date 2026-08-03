from __future__ import annotations

import re
from pathlib import Path

from s4mod.cli import build_parser, main


def test_parser_has_expected_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "scan" in help_text
    assert "run" in help_text
    assert "undo" in help_text


def test_scan_command_writes_reports_outside_mods(tmp_path: Path) -> None:
    mods = tmp_path / "The Sims 4" / "Mods"
    mods.mkdir(parents=True)
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    (mods / "Fictional.package").write_bytes(b"synthetic fixture")

    assert main(["scan", "--mods", str(mods), "--lang", "zh-CN"]) == 0

    runs = list((mods.parent / "S4ModSteward" / "runs").iterdir())
    assert len(runs) == 1
    assert {path.name for path in runs[0].iterdir()} == {
        "report.html",
        "inventory.csv",
        "report.json",
        "report.txt",
        "AI_HANDOFF.md",
    }
    assert not any(path.name.startswith("report.") for path in mods.iterdir())


def test_scan_rejects_output_outside_workspace(tmp_path: Path) -> None:
    mods = tmp_path / "Game" / "Mods"
    mods.mkdir(parents=True)
    outside = tmp_path / "outside-report"

    assert main(["scan", "--mods", str(mods), "--output", str(outside)]) == 2
    assert not outside.exists()


def test_run_dry_run_does_not_change_mods(tmp_path: Path) -> None:
    workspace = tmp_path / "The Sims 4"
    mods = workspace / "Mods"
    inbox = workspace / "Inbox"
    mods.mkdir(parents=True)
    inbox.mkdir()
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    (inbox / "Fictional.package").write_bytes(b"synthetic fixture")

    assert main(["run", "--mods", str(mods), "--inbox", str(inbox)]) == 0

    assert not (mods / "Fictional.package").exists()
    run = next((workspace / "S4ModSteward" / "runs").iterdir())
    assert (run / "plan.json").is_file()
    assert (run / "before.json").is_file()
    assert len(list((run / "staging").rglob("Fictional.package"))) == 1
    assert not (run / "manifest.json").exists()


def test_cli_apply_and_undo_delegate_to_core_services(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "The Sims 4"
    mods = workspace / "Mods"
    inbox = workspace / "Inbox"
    mods.mkdir(parents=True)
    inbox.mkdir()
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    (inbox / "Fictional.package").write_bytes(b"synthetic fixture")

    def exact_phrase(prompt: str) -> str:
        match = re.search(r"(APPLY|UNDO) [A-Za-z0-9-]+", prompt)
        assert match is not None
        return match.group(0)

    monkeypatch.setattr("builtins.input", exact_phrase)
    assert main(["run", "--mods", str(mods), "--inbox", str(inbox), "--apply"]) == 0
    assert (mods / "Fictional.package").read_bytes() == b"synthetic fixture"

    run = next((workspace / "S4ModSteward" / "runs").iterdir())
    assert main(["undo", "--mods", str(mods), "--run", str(run)]) == 0
    assert not (mods / "Fictional.package").exists()
    assert len(list((run / "staging").rglob("Fictional.package"))) == 1
