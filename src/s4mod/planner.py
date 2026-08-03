from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from .localization import Translator, load_folder_profile
from .models import (
    FileKind,
    InboxStage,
    PlanAction,
    PlanOperation,
    RunPlan,
    ScanSnapshot,
    StagedCandidate,
)
from .paths import validate_relative_path

MOD_KINDS = frozenset({FileKind.PACKAGE, FileKind.TS4SCRIPT})


def _operation(
    *,
    action: PlanAction,
    source: str,
    destination: str | None,
    reason: str,
    evidence: dict[str, object],
    requires_review: bool,
    source_sha256: str | None,
    target_sha256: str | None = None,
) -> PlanOperation:
    return PlanOperation(
        operation_id=str(uuid.uuid4()),
        action=action,
        source=source,
        destination=destination,
        reason=reason,
        evidence=evidence,
        requires_review=requires_review,
        source_sha256=source_sha256,
        target_sha256=target_sha256,
    )


def _destination(candidate: StagedCandidate, profile_name: str, profile: dict[str, object]) -> str:
    validate_relative_path(candidate.proposed_path)
    if profile_name == "neutral":
        return candidate.proposed_path
    categories = profile.get("categories")
    if not isinstance(categories, dict) or not isinstance(categories.get("manual_review"), str):
        raise TypeError(f"Folder profile '{profile_name}' has no manual_review category.")
    destination = f"{categories['manual_review']}/{candidate.proposed_path}"
    validate_relative_path(destination)
    return destination


def build_plan(
    before: ScanSnapshot,
    stage: InboxStage,
    *,
    profile_name: str = "neutral",
    run_id: str,
    now: datetime | None = None,
) -> RunPlan:
    profile = load_folder_profile(profile_name)
    normalized_profile = str(profile.get("locale", profile_name))
    now = now or datetime.now(UTC)
    current_by_hash: dict[str, list[str]] = defaultdict(list)
    current_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    current_by_relative: dict[str, tuple[str, str]] = {}
    for record in before.files:
        if record.kind not in MOD_KINDS or not record.sha256:
            continue
        current_by_hash[record.sha256].append(record.relative_path)
        current_by_name[record.name.casefold()].append((record.relative_path, record.sha256))
        current_by_relative[record.relative_path.casefold()] = (record.relative_path, record.sha256)

    destinations: dict[str, list[StagedCandidate]] = defaultdict(list)
    destination_by_source: dict[str, str] = {}
    for candidate in stage.candidates:
        if candidate.kind not in MOD_KINDS:
            continue
        destination = _destination(candidate, normalized_profile, profile)
        destination_by_source[candidate.source] = destination
        destinations[destination.casefold()].append(candidate)

    conflicting_sources: set[str] = set()
    duplicate_source_of: dict[str, str] = {}
    for candidates in destinations.values():
        if len(candidates) < 2:
            continue
        hashes = {candidate.sha256 for candidate in candidates}
        if len(hashes) > 1:
            conflicting_sources.update(candidate.source for candidate in candidates)
        else:
            first = candidates[0]
            for duplicate in candidates[1:]:
                duplicate_source_of[duplicate.source] = first.source

    operations: list[PlanOperation] = []
    for digest, paths in sorted(current_by_hash.items()):
        if len(paths) < 2:
            continue
        ordered = sorted(
            paths,
            key=lambda path: (len(validate_relative_path(path)) - 1, path.casefold()),
        )
        keeper = ordered[0]
        for duplicate_path in ordered[1:]:
            operations.append(
                _operation(
                    action=PlanAction.BACKUP,
                    source=duplicate_path,
                    destination=duplicate_path,
                    reason="exact_duplicate_backup",
                    evidence={"matching_file_kept": keeper, "sha256": digest},
                    requires_review=False,
                    source_sha256=digest,
                )
            )

    for candidate in stage.candidates:
        evidence: dict[str, object] = {
            "source_label": candidate.source_label,
            "size": candidate.size,
            "kind": candidate.kind.value,
        }
        if candidate.kind not in MOD_KINDS:
            operations.append(
                _operation(
                    action=PlanAction.REVIEW,
                    source=candidate.source,
                    destination=None,
                    reason="non_mod_file",
                    evidence=evidence,
                    requires_review=True,
                    source_sha256=candidate.sha256,
                )
            )
            continue

        destination = destination_by_source[candidate.source]
        if candidate.source in conflicting_sources:
            evidence["proposed_destination"] = destination
            evidence["conflicting_inbox_sources"] = [
                other.source_label
                for other in destinations[destination.casefold()]
                if other.source != candidate.source
            ]
            operations.append(
                _operation(
                    action=PlanAction.REVIEW,
                    source=candidate.source,
                    destination=destination,
                    reason="inbox_destination_conflict",
                    evidence=evidence,
                    requires_review=True,
                    source_sha256=candidate.sha256,
                )
            )
            continue
        if candidate.source in duplicate_source_of:
            evidence["duplicate_of_inbox_source"] = duplicate_source_of[candidate.source]
            operations.append(
                _operation(
                    action=PlanAction.SKIP,
                    source=candidate.source,
                    destination=destination,
                    reason="duplicate_in_inbox",
                    evidence=evidence,
                    requires_review=False,
                    source_sha256=candidate.sha256,
                )
            )
            continue
        if candidate.sha256 in current_by_hash:
            evidence["matching_mods_paths"] = sorted(
                current_by_hash[candidate.sha256], key=str.casefold
            )
            operations.append(
                _operation(
                    action=PlanAction.SKIP,
                    source=candidate.source,
                    destination=destination,
                    reason="exact_file_already_installed",
                    evidence=evidence,
                    requires_review=False,
                    source_sha256=candidate.sha256,
                )
            )
            continue

        destination_parts = validate_relative_path(destination)
        if candidate.kind == FileKind.TS4SCRIPT and len(destination_parts) - 1 > 1:
            evidence["folder_depth"] = len(destination_parts) - 1
            evidence["maximum"] = 1
            operations.append(
                _operation(
                    action=PlanAction.REVIEW,
                    source=candidate.source,
                    destination=destination,
                    reason="script_destination_too_deep",
                    evidence=evidence,
                    requires_review=True,
                    source_sha256=candidate.sha256,
                )
            )
            continue

        existing_relative = current_by_relative.get(destination.casefold())
        if existing_relative:
            existing_path, existing_hash = existing_relative
            evidence["existing_path"] = existing_path
            evidence["existing_sha256"] = existing_hash
            operations.append(
                _operation(
                    action=PlanAction.REPLACE,
                    source=candidate.source,
                    destination=existing_path,
                    reason="same_relative_path_different_content",
                    evidence=evidence,
                    requires_review=True,
                    source_sha256=candidate.sha256,
                    target_sha256=existing_hash,
                )
            )
            continue

        name_matches = current_by_name.get(
            candidate.proposed_path.rsplit("/", 1)[-1].casefold(), []
        )
        if name_matches:
            evidence["same_name_mods_paths"] = [path for path, _ in name_matches]
            evidence["same_name_sha256"] = {path: digest for path, digest in name_matches}
            operations.append(
                _operation(
                    action=PlanAction.REVIEW,
                    source=candidate.source,
                    destination=destination,
                    reason="same_name_different_content",
                    evidence=evidence,
                    requires_review=True,
                    source_sha256=candidate.sha256,
                )
            )
            continue

        localized_profile = normalized_profile != "neutral"
        operations.append(
            _operation(
                action=PlanAction.INSTALL,
                source=candidate.source,
                destination=destination,
                reason="new_file" if not localized_profile else "unclassified_category_suggestion",
                evidence=evidence,
                requires_review=localized_profile,
                source_sha256=candidate.sha256,
            )
        )

    for notice in stage.notices:
        operations.append(
            _operation(
                action=PlanAction.REVIEW,
                source=f"Inbox/{notice.source}",
                destination=None,
                reason=notice.code,
                evidence={"detail": notice.detail},
                requires_review=True,
                source_sha256=None,
            )
        )

    operations.sort(key=lambda item: (item.action.value, item.destination or "", item.source))
    return RunPlan(
        run_id=run_id,
        created_at=now.isoformat(timespec="seconds"),
        profile=normalized_profile,
        operations=tuple(operations),
    )


def render_plan_text(plan: RunPlan, translator: Translator) -> str:
    counts: dict[PlanAction, int] = defaultdict(int)
    for operation in plan.operations:
        counts[operation.action] += 1
    lines = [
        translator.text("plan.title"),
        f"{translator.text('report.run_id')}: {plan.run_id}",
        f"{translator.text('plan.profile')}: {plan.profile}",
        f"{translator.text('plan.default_dry_run')}: true",
        "",
    ]
    for action in PlanAction:
        lines.append(f"- {translator.text(f'plan.action.{action.value}')}: {counts[action]}")
    lines.append("")
    for operation in plan.operations:
        destination = operation.destination or "—"
        lines.extend(
            [
                f"[{operation.action.value}] {operation.operation_id}",
                f"  {translator.text('plan.source')}: {operation.source}",
                f"  {translator.text('plan.destination')}: {destination}",
                f"  {translator.text('plan.reason')}: {operation.reason}",
                (
                    f"  {translator.text('plan.requires_review')}: "
                    f"{str(operation.requires_review).lower()}"
                ),
            ]
        )
    return "\n".join(lines) + "\n"
