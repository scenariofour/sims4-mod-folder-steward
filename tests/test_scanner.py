from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from s4mod.models import FindingCode
from s4mod.scanner import scan_mods


def _synthetic_mods(tmp_path: Path) -> Path:
    mods = tmp_path / "The Sims 4" / "Mods"
    (mods / "CreatorA" / "Nested").mkdir(parents=True)
    (mods / "CreatorB").mkdir()
    (mods / "EmptyFolder").mkdir()
    (mods / "resource.cfg").write_text("Priority 500", encoding="utf-8")
    (mods / "Loose.package").write_bytes(b"duplicate bytes")
    (mods / "CreatorA" / "Duplicate.package").write_bytes(b"duplicate bytes")
    (mods / "CreatorA" / "Conflict.package").write_bytes(b"version a")
    (mods / "CreatorB" / "conflict.package").write_bytes(b"version b")
    (mods / "CreatorA" / "Nested" / "Deep.ts4script").write_bytes(b"script")
    (mods / "downloads.zip").write_bytes(b"not a real archive")
    return mods


def test_scan_detects_required_findings_without_modifying_mods(tmp_path: Path) -> None:
    mods = _synthetic_mods(tmp_path)
    before = sorted(path.relative_to(mods).as_posix() for path in mods.rglob("*"))

    snapshot = scan_mods(
        mods,
        language="en",
        run_id="scan-test",
        now=datetime(2026, 8, 3, tzinfo=UTC),
        platform_name="TestOS",
    )

    after = sorted(path.relative_to(mods).as_posix() for path in mods.rglob("*"))
    codes = {finding.code for finding in snapshot.findings}
    assert before == after
    assert snapshot.mods_root == "<MODS_FOLDER>"
    assert snapshot.summary.package_files == 4
    assert snapshot.summary.ts4script_files == 1
    assert snapshot.summary.archives == 1
    assert snapshot.summary.exact_duplicate_groups == 1
    assert snapshot.summary.name_conflict_groups == 1
    assert snapshot.summary.script_depth_issues == 1
    assert snapshot.summary.root_loose_files == 2
    assert snapshot.summary.empty_directories == 1
    assert FindingCode.EXACT_DUPLICATE in codes
    assert FindingCode.NAME_CONFLICT in codes
    assert FindingCode.SCRIPT_TOO_DEEP in codes
    assert FindingCode.ARCHIVE_IN_MODS in codes
    assert FindingCode.ROOT_LOOSE_FILE in codes
    assert FindingCode.EMPTY_DIRECTORY in codes


def test_scan_does_not_follow_file_or_directory_symlinks(tmp_path: Path) -> None:
    mods = tmp_path / "Game" / "Mods"
    outside = tmp_path / "private"
    mods.mkdir(parents=True)
    outside.mkdir()
    (outside / "Secret.package").write_bytes(b"private bytes")
    (mods / "LinkedFolder").symlink_to(outside, target_is_directory=True)
    (mods / "Linked.package").symlink_to(outside / "Secret.package")

    snapshot = scan_mods(mods, run_id="scan-links")

    assert snapshot.summary.unsafe_symlinks == 2
    linked = next(record for record in snapshot.files if record.name == "Linked.package")
    assert linked.sha256 is None
    assert all("Secret.package" not in record.relative_path for record in snapshot.files)


def test_symlinked_resource_cfg_is_unsafe_and_does_not_count_as_protected(tmp_path: Path) -> None:
    mods = tmp_path / "Game" / "Mods"
    outside = tmp_path / "resource.cfg"
    mods.mkdir(parents=True)
    outside.write_text("external", encoding="utf-8")
    (mods / "resource.cfg").symlink_to(outside)

    snapshot = scan_mods(mods, run_id="scan-resource-link")
    codes = [finding.code for finding in snapshot.findings]

    assert FindingCode.UNSAFE_SYMLINK in codes
    assert FindingCode.RESOURCE_CFG_MISSING in codes
