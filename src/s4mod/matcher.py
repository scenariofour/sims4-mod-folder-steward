from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .models import FileKind, FileRecord

HASHED_MOD_KINDS = frozenset({FileKind.PACKAGE, FileKind.TS4SCRIPT})


def exact_duplicate_groups(records: Iterable[FileRecord]) -> list[tuple[str, tuple[str, ...]]]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for record in records:
        if record.kind in HASHED_MOD_KINDS and record.sha256:
            by_hash[record.sha256].append(record.relative_path)
    return sorted(
        (digest, tuple(sorted(paths, key=str.casefold)))
        for digest, paths in by_hash.items()
        if len(paths) > 1
    )


def name_conflict_groups(records: Iterable[FileRecord]) -> list[tuple[str, tuple[str, ...]]]:
    by_name: dict[str, list[FileRecord]] = defaultdict(list)
    for record in records:
        if record.kind in HASHED_MOD_KINDS and record.sha256:
            by_name[record.name.casefold()].append(record)

    conflicts: list[tuple[str, tuple[str, ...]]] = []
    for records_with_name in by_name.values():
        if len({record.sha256 for record in records_with_name}) > 1:
            display_name = min((record.name for record in records_with_name), key=str.casefold)
            paths = tuple(
                sorted((record.relative_path for record in records_with_name), key=str.casefold)
            )
            conflicts.append((display_name, paths))
    return sorted(conflicts, key=lambda item: item[0].casefold())
