from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from s4mod.localization import Translator
from s4mod.privacy import PathRedactor
from s4mod.reports import REPORT_FILENAMES, write_scan_reports
from s4mod.scanner import scan_mods


def test_reports_are_bilingual_relative_and_anonymized(tmp_path: Path) -> None:
    workspace = tmp_path / "Private User" / "The Sims 4"
    mods = workspace / "Mods"
    run = workspace / "S4ModSteward" / "runs" / "scan-test"
    mods.mkdir(parents=True)
    run.mkdir(parents=True)
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    (mods / "FictionalCreator" / "示例.package").parent.mkdir()
    (mods / "FictionalCreator" / "示例.package").write_bytes(b"synthetic")
    snapshot = scan_mods(
        mods,
        language="zh-CN",
        run_id="scan-test",
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )
    redactor = PathRedactor.for_run(
        mods_root=mods,
        workspace_root=workspace,
        run_root=run,
        home=tmp_path / "Private User",
        environ={"USER": "Private User"},
    )

    written = write_scan_reports(
        snapshot,
        run,
        translator=Translator.load("zh-CN"),
        redactor=redactor,
    )

    assert set(written) == set(REPORT_FILENAMES)
    combined = "\n".join(path.read_text(encoding="utf-8") for path in written.values())
    assert str(workspace) not in combined
    assert str(mods) not in combined
    assert "Private User" not in combined
    assert "<MODS_FOLDER>" in combined
    assert "Sims 4 Mods 扫描报告" in combined
    assert "FictionalCreator/示例.package" in combined

    schema = json.loads((Path(__file__).parents[1] / "schemas/snapshot.schema.json").read_text())
    report = json.loads(written["report.json"].read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)


def test_english_report_uses_english_labels(tmp_path: Path) -> None:
    workspace = tmp_path / "Game"
    mods = workspace / "Mods"
    run = workspace / "Run"
    mods.mkdir(parents=True)
    run.mkdir()
    snapshot = scan_mods(mods, language="en", run_id="scan-en")
    redactor = PathRedactor.for_run(
        mods_root=mods,
        workspace_root=workspace,
        run_root=run,
        home=tmp_path,
        environ={},
    )

    write_scan_reports(snapshot, run, translator=Translator.load("en"), redactor=redactor)

    assert "Sims 4 Mods scan report" in (run / "report.txt").read_text(encoding="utf-8")
