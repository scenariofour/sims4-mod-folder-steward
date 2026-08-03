from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from s4mod.archives import (
    ArchiveLimits,
    ArchiveSafetyError,
    safe_extract_zip,
    stage_inbox,
)


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_safe_extract_and_stage_nested_zip(tmp_path: Path) -> None:
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    nested = tmp_path / "nested.zip"
    _zip(nested, {"Creator/Nested.package": b"nested"})
    _zip(inbox / "bundle.zip", {"Top.package": b"top", "nested.zip": nested.read_bytes()})
    (inbox / "manual.rar").write_bytes(b"synthetic, not a real archive")

    stage = stage_inbox(inbox, tmp_path / "run" / "staging")

    assert {item.proposed_path for item in stage.candidates} == {
        "Creator/Nested.package",
        "Top.package",
    }
    assert [notice.code for notice in stage.notices] == ["unsupported_archive"]
    assert all(item.source.startswith("staging/") for item in stage.candidates)


@pytest.mark.parametrize(
    "unsafe_name",
    ["../escape.package", "/absolute.package", "C:\\bad.package", "\\\\server\\bad.package"],
)
def test_zip_path_escape_is_rejected(tmp_path: Path, unsafe_name: str) -> None:
    archive = tmp_path / "unsafe.zip"
    _zip(archive, {unsafe_name: b"unsafe"})
    destination = tmp_path / "extract"

    with pytest.raises(ArchiveSafetyError, match="unsafe path"):
        safe_extract_zip(archive, destination)
    assert not (tmp_path / "escape.package").exists()


def test_zip_symlink_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link.package")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(info, "target.package")

    with pytest.raises(ArchiveSafetyError, match="symbolic links"):
        safe_extract_zip(archive, tmp_path / "extract")


def test_zip_duplicate_casefold_path_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("Creator/Item.package", b"one")
        output.writestr("creator/item.package", b"two")

    with pytest.raises(ArchiveSafetyError, match="duplicate path"):
        safe_extract_zip(archive, tmp_path / "extract")


def test_encrypted_zip_flag_is_rejected_before_reading(tmp_path: Path) -> None:
    archive = tmp_path / "encrypted-flag.zip"
    _zip(archive, {"file.package": b"content"})
    data = bytearray(archive.read_bytes())
    local = data.index(b"PK\x03\x04")
    central = data.index(b"PK\x01\x02")
    data[local + 6] |= 0x01
    data[central + 8] |= 0x01
    archive.write_bytes(data)

    with pytest.raises(ArchiveSafetyError, match="Encrypted ZIP"):
        safe_extract_zip(archive, tmp_path / "extract")


def test_zip_limits_are_checked_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "large.zip"
    _zip(archive, {"large.package": b"A" * 200})

    with pytest.raises(ArchiveSafetyError, match="too large"):
        safe_extract_zip(
            archive,
            tmp_path / "extract",
            limits=ArchiveLimits(max_file_size=100),
        )
    assert not (tmp_path / "extract" / "large.package").exists()


def test_zip_compression_ratio_limit_is_enforced(tmp_path: Path) -> None:
    archive = tmp_path / "compressed.zip"
    _zip(archive, {"compressed.package": b"A" * 10_000})

    with pytest.raises(ArchiveSafetyError, match="compression ratio"):
        safe_extract_zip(
            archive,
            tmp_path / "extract",
            limits=ArchiveLimits(max_compression_ratio=2),
        )


def test_zip_member_count_and_total_size_limits_are_enforced(tmp_path: Path) -> None:
    archive = tmp_path / "limits.zip"
    _zip(archive, {"one.package": b"123", "two.package": b"456"})

    with pytest.raises(ArchiveSafetyError, match="too many entries"):
        safe_extract_zip(
            archive,
            tmp_path / "count-extract",
            limits=ArchiveLimits(max_members=1),
        )
    with pytest.raises(ArchiveSafetyError, match="expanded size"):
        safe_extract_zip(
            archive,
            tmp_path / "size-extract",
            limits=ArchiveLimits(max_total_size=5),
        )


def test_nested_archive_limit_becomes_review_notice(tmp_path: Path) -> None:
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    nested = tmp_path / "nested.zip"
    _zip(nested, {"file.package": b"content"})
    _zip(inbox / "outer.zip", {"nested.zip": nested.read_bytes()})

    stage = stage_inbox(
        inbox,
        tmp_path / "run" / "staging",
        limits=ArchiveLimits(max_nesting=0),
    )

    assert stage.candidates == ()
    assert [notice.code for notice in stage.notices] == ["archive_nesting_limit"]


def test_inbox_symlink_is_rejected(tmp_path: Path) -> None:
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    outside = tmp_path / "outside.package"
    outside.write_bytes(b"outside")
    (inbox / "link.package").symlink_to(outside)

    with pytest.raises(ArchiveSafetyError, match="symbolic links"):
        stage_inbox(inbox, tmp_path / "run" / "staging")
