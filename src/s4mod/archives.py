from __future__ import annotations

import os
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .hashing import sha256_file
from .models import FileKind, InboxNotice, InboxStage, StagedCandidate
from .paths import PathSafetyError, safe_join

ZIP_EXTENSION = ".zip"
UNSUPPORTED_ARCHIVE_EXTENSIONS = frozenset({".rar", ".7z"})
MOD_KINDS = {".package": FileKind.PACKAGE, ".ts4script": FileKind.TS4SCRIPT}
IGNORED_NAMES = frozenset({".ds_store", "thumbs.db"})


class ArchiveSafetyError(ValueError):
    """Raised when an archive or Inbox entry is unsafe to stage."""


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_members: int = 100_000
    max_file_size: int = 2 * 1024 * 1024 * 1024
    max_total_size: int = 4 * 1024 * 1024 * 1024
    max_compression_ratio: int = 1_000
    max_nesting: int = 5


def _member_is_link_or_special(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    if not mode:
        return False
    file_type = stat.S_IFMT(mode)
    return stat.S_ISLNK(mode) or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}


def safe_extract_zip(
    archive: Path,
    destination: Path,
    *,
    limits: ArchiveLimits | None = None,
) -> tuple[Path, ...]:
    limits = limits or ArchiveLimits()
    destination.mkdir(parents=True, exist_ok=False)
    extracted: list[Path] = []
    seen_names: set[str] = set()

    try:
        zip_file = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise ArchiveSafetyError(f"Invalid ZIP archive: {archive.name}") from error

    with zip_file:
        members = zip_file.infolist()
        if len(members) > limits.max_members:
            raise ArchiveSafetyError(
                f"ZIP contains too many entries ({len(members)} > {limits.max_members})."
            )

        total_size = 0
        validated: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in members:
            try:
                target = safe_join(destination, info.filename)
            except PathSafetyError as error:
                raise ArchiveSafetyError(
                    f"ZIP contains an unsafe path: {info.filename!r}"
                ) from error
            normalized_name = target.relative_to(destination).as_posix().casefold()
            if normalized_name in seen_names:
                raise ArchiveSafetyError(f"ZIP contains a duplicate path: {info.filename!r}")
            seen_names.add(normalized_name)
            if info.flag_bits & 0x1:
                raise ArchiveSafetyError(
                    f"Encrypted ZIP entries are not supported: {info.filename!r}"
                )
            if _member_is_link_or_special(info):
                raise ArchiveSafetyError(
                    f"ZIP symbolic links and special files are not allowed: {info.filename!r}"
                )
            if info.file_size > limits.max_file_size:
                raise ArchiveSafetyError(f"ZIP entry is too large: {info.filename!r}")
            total_size += info.file_size
            if total_size > limits.max_total_size:
                raise ArchiveSafetyError("ZIP expanded size exceeds the configured limit.")
            if (
                info.file_size > 0
                and info.file_size / max(info.compress_size, 1) > limits.max_compression_ratio
            ):
                raise ArchiveSafetyError(f"ZIP compression ratio is unsafe: {info.filename!r}")
            validated.append((info, target))

        for info, target in validated:
            if info.is_dir() or info.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with zip_file.open(info, "r") as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > info.file_size or written > limits.max_file_size:
                            raise ArchiveSafetyError(
                                f"ZIP entry exceeded its declared size: {info.filename!r}"
                            )
                        output.write(chunk)
            except OSError as error:
                raise ArchiveSafetyError(
                    f"Could not extract ZIP entry: {info.filename!r}"
                ) from error
            if written != info.file_size:
                raise ArchiveSafetyError(f"ZIP entry size mismatch: {info.filename!r}")
            extracted.append(target)
    return tuple(extracted)


def _kind(path: Path) -> FileKind:
    return MOD_KINDS.get(path.suffix.casefold(), FileKind.OTHER)


def _reject_symlinks(root: Path) -> None:
    for current_text, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(current_text)
        for name in [*directory_names, *file_names]:
            path = current / name
            if path.is_symlink():
                raise ArchiveSafetyError(
                    f"Inbox symbolic links are not allowed: {path.relative_to(root).as_posix()}"
                )


def stage_inbox(
    inbox_root: Path,
    staging_root: Path,
    *,
    limits: ArchiveLimits | None = None,
    source_base: Path | None = None,
) -> InboxStage:
    limits = limits or ArchiveLimits()
    if inbox_root.is_symlink():
        raise ArchiveSafetyError(f"Inbox symbolic links are not allowed: {inbox_root}")
    inbox_root = inbox_root.resolve(strict=True)
    if not inbox_root.is_dir():
        raise NotADirectoryError(f"Inbox is not a directory: {inbox_root}")
    if staging_root.exists():
        raise FileExistsError(f"Staging directory already exists: {staging_root}")
    staging_root.mkdir(parents=True)
    source_base = source_base or staging_root.parent
    if not staging_root.is_relative_to(source_base):
        raise ArchiveSafetyError("Staging directory must be inside its source base.")
    _reject_symlinks(inbox_root)

    candidates: list[StagedCandidate] = []
    notices: list[InboxNotice] = []
    archive_counter = 0

    def add_candidate(source: Path, physical: Path, proposed: str, label: str) -> None:
        physical.parent.mkdir(parents=True, exist_ok=True)
        if source != physical:
            if physical.exists():
                raise ArchiveSafetyError(f"Staging path collision: {proposed}")
            shutil.copy2(source, physical)
        candidates.append(
            StagedCandidate(
                source=physical.relative_to(source_base).as_posix(),
                proposed_path=proposed,
                source_label=label,
                kind=_kind(physical),
                size=physical.stat().st_size,
                sha256=sha256_file(physical),
            )
        )

    def unsupported_notice(label: str, suffix: str) -> None:
        notices.append(
            InboxNotice(
                source=label,
                code="unsupported_archive",
                detail=(
                    f"{suffix.upper()} is not extracted automatically in v0.1. "
                    "Extract it manually into Inbox and run again."
                ),
            )
        )

    def process_archive(archive: Path, label: str, depth: int) -> None:
        nonlocal archive_counter
        if depth > limits.max_nesting:
            notices.append(
                InboxNotice(
                    source=label,
                    code="archive_nesting_limit",
                    detail=f"Nested archives deeper than {limits.max_nesting} require manual review.",
                )
            )
            return
        archive_counter += 1
        extraction_root = staging_root / "extracted" / f"archive-{archive_counter:04d}"
        safe_extract_zip(archive, extraction_root, limits=limits)
        _reject_symlinks(extraction_root)
        for path in sorted(extraction_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not path.is_file():
                continue
            relative = path.relative_to(extraction_root).as_posix()
            member_label = f"{label}!{relative}"
            suffix = path.suffix.casefold()
            if suffix == ZIP_EXTENSION:
                process_archive(path, member_label, depth + 1)
            elif suffix in UNSUPPORTED_ARCHIVE_EXTENSIONS:
                unsupported_notice(member_label, suffix)
            else:
                add_candidate(path, path, relative, member_label)

    direct_root = staging_root / "direct"
    for path in sorted(inbox_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(inbox_root).as_posix()
        if path.name.casefold() in IGNORED_NAMES:
            continue
        suffix = path.suffix.casefold()
        if suffix == ZIP_EXTENSION:
            process_archive(path, relative, 0)
        elif suffix in UNSUPPORTED_ARCHIVE_EXTENSIONS:
            unsupported_notice(relative, suffix)
        else:
            add_candidate(path, direct_root / Path(relative), relative, relative)

    candidates.sort(key=lambda candidate: (candidate.proposed_path.casefold(), candidate.source))
    notices.sort(key=lambda notice: (notice.source.casefold(), notice.code))
    return InboxStage(candidates=tuple(candidates), notices=tuple(notices))
