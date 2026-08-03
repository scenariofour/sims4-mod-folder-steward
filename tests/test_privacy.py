from __future__ import annotations

from pathlib import Path

from s4mod.privacy import PathRedactor


def test_redactor_replaces_longest_paths_and_username(tmp_path: Path) -> None:
    home = tmp_path / "private-user"
    workspace = home / "Documents" / "The Sims 4"
    mods = workspace / "Mods"
    run = workspace / "S4ModSteward" / "runs" / "scan"
    redactor = PathRedactor.for_run(
        mods_root=mods,
        workspace_root=workspace,
        run_root=run,
        home=home,
        environ={"USER": "private-user"},
    )

    source = f"{run}/report.json {mods}/Creator/file.package {home} private-user"
    redacted = redactor.redact(source)

    assert str(home) not in redacted
    assert "private-user" not in redacted
    assert "<RUN_FOLDER>/report.json" in redacted
    assert "<MODS_FOLDER>/Creator/file.package" in redacted
