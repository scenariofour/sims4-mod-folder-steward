from __future__ import annotations

from pathlib import Path

from .models import PlanOperation
from .paths import safe_join


def replacement_quarantine_relative(operation: PlanOperation) -> str:
    if operation.destination is None:
        raise ValueError("A replacement operation requires a destination.")
    return f"quarantine/replaced/{operation.operation_id}/{operation.destination}"


def replacement_quarantine_path(run_directory: Path, operation: PlanOperation) -> Path:
    return safe_join(run_directory, replacement_quarantine_relative(operation))


def duplicate_quarantine_relative(operation: PlanOperation) -> str:
    if operation.destination is None:
        raise ValueError("A duplicate backup operation requires a destination.")
    return f"quarantine/duplicates/{operation.operation_id}/{operation.destination}"
