from __future__ import annotations

import os
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .hashing import sha256_file
from .matcher import exact_duplicate_groups, name_conflict_groups
from .models import (
    FileKind,
    FileRecord,
    Finding,
    FindingCode,
    ScanSnapshot,
    ScanSummary,
    Severity,
)
from .paths import validate_mods_path

MOD_EXTENSIONS = {".package": FileKind.PACKAGE, ".ts4script": FileKind.TS4SCRIPT}
ARCHIVE_EXTENSIONS = frozenset({".zip", ".rar", ".7z"})
IGNORED_ROOT_FILES = frozenset({".ds_store", "thumbs.db"})
PROTECTED_ROOT_FILES = frozenset({"resource.cfg"})


def _kind_for(path: Path, relative: Path) -> FileKind:
    if len(relative.parts) == 1 and path.name.casefold() in PROTECTED_ROOT_FILES:
        return FileKind.PROTECTED
    suffix = path.suffix.casefold()
    if suffix in MOD_EXTENSIONS:
        return MOD_EXTENSIONS[suffix]
    if suffix in ARCHIVE_EXTENSIONS:
        return FileKind.ARCHIVE
    return FileKind.OTHER


def _new_run_id(now: datetime) -> str:
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    return f"scan-{timestamp}-{uuid.uuid4().hex[:8]}"


def scan_mods(
    mods_root: Path,
    *,
    language: str = "en",
    run_id: str | None = None,
    now: datetime | None = None,
    platform_name: str | None = None,
) -> ScanSnapshot:
    mods_root = validate_mods_path(mods_root)
    now = now or datetime.now(UTC)
    run_id = run_id or _new_run_id(now)
    records: list[FileRecord] = []
    findings: list[Finding] = []
    empty_directories: list[str] = []
    protected_resource_found = False

    for root_text, directory_names, file_names in os.walk(mods_root, followlinks=False):
        root = Path(root_text)
        directory_names.sort(key=str.casefold)
        file_names.sort(key=str.casefold)
        original_directory_names = list(directory_names)

        for directory_name in original_directory_names:
            directory = root / directory_name
            if directory.is_symlink():
                relative = directory.relative_to(mods_root).as_posix()
                findings.append(
                    Finding(
                        code=FindingCode.UNSAFE_SYMLINK,
                        severity=Severity.REVIEW,
                        paths=(relative,),
                        evidence={"entry_type": "directory_symlink"},
                    )
                )
                directory_names.remove(directory_name)

        if root != mods_root and not original_directory_names and not file_names:
            empty_directories.append(root.relative_to(mods_root).as_posix())

        for file_name in file_names:
            path = root / file_name
            relative_path = path.relative_to(mods_root)
            relative = relative_path.as_posix()
            folder_depth = len(relative_path.parts) - 1
            kind = _kind_for(path, relative_path)

            try:
                stat = path.lstat()
            except OSError as error:
                findings.append(
                    Finding(
                        code=FindingCode.READ_ERROR,
                        severity=Severity.REVIEW,
                        paths=(relative,),
                        evidence={"error_type": type(error).__name__},
                    )
                )
                continue

            digest: str | None = None
            is_symlink = path.is_symlink()
            if is_symlink:
                findings.append(
                    Finding(
                        code=FindingCode.UNSAFE_SYMLINK,
                        severity=Severity.REVIEW,
                        paths=(relative,),
                        evidence={"entry_type": "file_symlink"},
                    )
                )
            elif kind in {FileKind.PACKAGE, FileKind.TS4SCRIPT}:
                try:
                    digest = sha256_file(path)
                except OSError as error:
                    findings.append(
                        Finding(
                            code=FindingCode.READ_ERROR,
                            severity=Severity.REVIEW,
                            paths=(relative,),
                            evidence={"error_type": type(error).__name__},
                        )
                    )
            elif kind == FileKind.PROTECTED:
                protected_resource_found = True

            records.append(
                FileRecord(
                    relative_path=relative,
                    name=file_name,
                    kind=kind,
                    size=stat.st_size,
                    sha256=digest,
                    modified_ns=max(0, stat.st_mtime_ns),
                    folder_depth=folder_depth,
                )
            )

            if kind == FileKind.TS4SCRIPT and folder_depth > 1:
                findings.append(
                    Finding(
                        code=FindingCode.SCRIPT_TOO_DEEP,
                        severity=Severity.REVIEW,
                        paths=(relative,),
                        evidence={"folder_depth": folder_depth, "maximum": 1},
                    )
                )
            if kind == FileKind.ARCHIVE:
                findings.append(
                    Finding(
                        code=FindingCode.ARCHIVE_IN_MODS,
                        severity=Severity.WARNING,
                        paths=(relative,),
                        evidence={"extension": path.suffix.casefold()},
                    )
                )
            if (
                folder_depth == 0
                and kind != FileKind.PROTECTED
                and file_name.casefold() not in IGNORED_ROOT_FILES
            ):
                findings.append(
                    Finding(
                        code=FindingCode.ROOT_LOOSE_FILE,
                        severity=Severity.WARNING,
                        paths=(relative,),
                        evidence={"kind": kind.value},
                    )
                )

    records.sort(key=lambda record: record.relative_path.casefold())

    duplicate_groups = exact_duplicate_groups(records)
    for digest, paths in duplicate_groups:
        findings.append(
            Finding(
                code=FindingCode.EXACT_DUPLICATE,
                severity=Severity.REVIEW,
                paths=paths,
                evidence={"sha256": digest},
            )
        )

    conflict_groups = name_conflict_groups(records)
    records_by_path = {record.relative_path: record for record in records}
    for name, paths in conflict_groups:
        findings.append(
            Finding(
                code=FindingCode.NAME_CONFLICT,
                severity=Severity.REVIEW,
                paths=paths,
                evidence={
                    "name": name,
                    "sha256": {path: records_by_path[path].sha256 for path in paths},
                },
            )
        )

    for relative in sorted(empty_directories, key=str.casefold):
        findings.append(
            Finding(
                code=FindingCode.EMPTY_DIRECTORY,
                severity=Severity.INFO,
                paths=(relative,),
                evidence={},
            )
        )

    if not protected_resource_found:
        findings.append(
            Finding(
                code=FindingCode.RESOURCE_CFG_MISSING,
                severity=Severity.WARNING,
                paths=(),
                evidence={"protected_name": "resource.cfg"},
            )
        )

    findings.sort(key=lambda finding: (finding.code.value, tuple(map(str.casefold, finding.paths))))
    summary = ScanSummary(
        files_total=len(records),
        package_files=sum(record.kind == FileKind.PACKAGE for record in records),
        ts4script_files=sum(record.kind == FileKind.TS4SCRIPT for record in records),
        archives=sum(record.kind == FileKind.ARCHIVE for record in records),
        other_files=sum(record.kind in {FileKind.OTHER, FileKind.PROTECTED} for record in records),
        exact_duplicate_groups=len(duplicate_groups),
        name_conflict_groups=len(conflict_groups),
        script_depth_issues=sum(
            finding.code == FindingCode.SCRIPT_TOO_DEEP for finding in findings
        ),
        root_loose_files=sum(
            finding.code == FindingCode.ROOT_LOOSE_FILE for finding in findings
        ),
        empty_directories=len(empty_directories),
        unsafe_symlinks=sum(
            finding.code == FindingCode.UNSAFE_SYMLINK for finding in findings
        ),
    )
    return ScanSnapshot(
        run_id=run_id,
        created_at=now.isoformat(timespec="seconds"),
        language=language,
        platform=platform_name or platform.system(),
        mods_root="<MODS_FOLDER>",
        files=tuple(records),
        findings=tuple(findings),
        summary=summary,
    )
