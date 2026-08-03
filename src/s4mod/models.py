from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

SNAPSHOT_SCHEMA_VERSION = "1.0"


class FileKind(StrEnum):
    PACKAGE = "package"
    TS4SCRIPT = "ts4script"
    ARCHIVE = "archive"
    PROTECTED = "protected"
    OTHER = "other"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    REVIEW = "review"


class FindingCode(StrEnum):
    EXACT_DUPLICATE = "exact_duplicate"
    NAME_CONFLICT = "name_conflict"
    SCRIPT_TOO_DEEP = "script_too_deep"
    ARCHIVE_IN_MODS = "archive_in_mods"
    ROOT_LOOSE_FILE = "root_loose_file"
    EMPTY_DIRECTORY = "empty_directory"
    UNSAFE_SYMLINK = "unsafe_symlink"
    READ_ERROR = "read_error"
    RESOURCE_CFG_MISSING = "resource_cfg_missing"


class PlanAction(StrEnum):
    INSTALL = "install"
    REPLACE = "replace"
    BACKUP = "backup"
    SKIP = "skip"
    REVIEW = "review"


class OperationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ManifestStatus(StrEnum):
    APPLYING = "applying"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


@dataclass(frozen=True, slots=True)
class FileRecord:
    relative_path: str
    name: str
    kind: FileKind
    size: int
    sha256: str | None
    modified_ns: int
    folder_depth: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Finding:
    code: FindingCode
    severity: Severity
    paths: tuple[str, ...]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScanSummary:
    files_total: int
    package_files: int
    ts4script_files: int
    archives: int
    other_files: int
    exact_duplicate_groups: int
    name_conflict_groups: int
    script_depth_issues: int
    root_loose_files: int
    empty_directories: int
    unsafe_symlinks: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScanSnapshot:
    run_id: str
    created_at: str
    language: str
    platform: str
    mods_root: str
    files: tuple[FileRecord, ...]
    findings: tuple[Finding, ...]
    summary: ScanSummary
    schema_version: str = SNAPSHOT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "language": self.language,
            "platform": self.platform,
            "mods_root": self.mods_root,
            "summary": self.summary.to_dict(),
            "files": [record.to_dict() for record in self.files],
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True, slots=True)
class StagedCandidate:
    source: str
    proposed_path: str
    source_label: str
    kind: FileKind
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class InboxNotice:
    source: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class InboxStage:
    candidates: tuple[StagedCandidate, ...]
    notices: tuple[InboxNotice, ...]


@dataclass(frozen=True, slots=True)
class PlanOperation:
    operation_id: str
    action: PlanAction
    source: str
    destination: str | None
    reason: str
    evidence: dict[str, Any]
    requires_review: bool
    source_sha256: str | None
    target_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RunPlan:
    run_id: str
    created_at: str
    profile: str
    operations: tuple[PlanOperation, ...]
    schema_version: str = "1.0"
    workspace_root: str = "<SIMS4_WORKSPACE>"
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "workspace_root": self.workspace_root,
            "dry_run": self.dry_run,
            "profile": self.profile,
            "operations": [operation.to_dict() for operation in self.operations],
        }


@dataclass(slots=True)
class ManifestOperation:
    operation_id: str
    action: PlanAction
    source: str
    destination: str
    status: OperationStatus
    source_sha256: str
    target_before_sha256: str | None = None
    quarantine_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunManifest:
    run_id: str
    created_at: str
    status: ManifestStatus
    operations: list[ManifestOperation]
    schema_version: str = "1.0"
    workspace_root: str = "<SIMS4_WORKSPACE>"
    before_snapshot: str = "before.json"
    after_snapshot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "workspace_root": self.workspace_root,
            "status": self.status,
            "before_snapshot": self.before_snapshot,
            "after_snapshot": self.after_snapshot,
            "operations": [operation.to_dict() for operation in self.operations],
        }


def run_manifest_from_dict(document: dict[str, Any]) -> RunManifest:
    try:
        operations_data = document["operations"]
        if not isinstance(operations_data, list):
            raise TypeError("operations is not a list")
        operations = [
            ManifestOperation(
                operation_id=str(item["operation_id"]),
                action=PlanAction(item["action"]),
                source=str(item["source"]),
                destination=str(item["destination"]),
                status=OperationStatus(item["status"]),
                source_sha256=str(item["source_sha256"]),
                target_before_sha256=(
                    str(item["target_before_sha256"])
                    if item.get("target_before_sha256") is not None
                    else None
                ),
                quarantine_path=(
                    str(item["quarantine_path"])
                    if item.get("quarantine_path") is not None
                    else None
                ),
                error=str(item["error"]) if item.get("error") is not None else None,
            )
            for item in operations_data
            if isinstance(item, dict)
        ]
        if len(operations) != len(operations_data):
            raise TypeError("operation is not an object")
        return RunManifest(
            run_id=str(document["run_id"]),
            created_at=str(document["created_at"]),
            status=ManifestStatus(document["status"]),
            operations=operations,
            schema_version=str(document["schema_version"]),
            workspace_root=str(document["workspace_root"]),
            before_snapshot=str(document["before_snapshot"]),
            after_snapshot=(
                str(document["after_snapshot"])
                if document.get("after_snapshot") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Invalid run manifest document.") from error
