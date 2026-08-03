from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]


def test_all_json_schemas_are_valid() -> None:
    for path in sorted((ROOT / "schemas").glob("*.schema.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_plan_and_manifest_examples_validate() -> None:
    schemas = ROOT / "schemas"
    operation_id = "12345678-1234-5678-9234-567812345678"
    plan = {
        "schema_version": "1.0",
        "run_id": "run-test",
        "created_at": "2026-08-03T00:00:00+00:00",
        "workspace_root": "<SIMS4_WORKSPACE>",
        "dry_run": True,
        "profile": "neutral",
        "operations": [
            {
                "operation_id": operation_id,
                "action": "review",
                "source": "Inbox/Fictional.package",
                "destination": None,
                "reason": "unknown",
                "evidence": {},
                "requires_review": True,
                "source_sha256": "0" * 64,
                "target_sha256": None,
            }
        ],
    }
    manifest = {
        "schema_version": "1.0",
        "run_id": "run-test",
        "created_at": "2026-08-03T00:00:00+00:00",
        "workspace_root": "<SIMS4_WORKSPACE>",
        "status": "applied",
        "before_snapshot": "before.json",
        "after_snapshot": "after.json",
        "operations": [
            {
                "operation_id": operation_id,
                "action": "replace",
                "source": "staging/direct/Fictional.package",
                "destination": "Fictional.package",
                "status": "completed",
                "source_sha256": "0" * 64,
                "target_before_sha256": "1" * 64,
                "quarantine_path": "quarantine/replaced/op/Fictional.package",
                "error": None,
            }
        ],
    }

    for filename, document in (("plan.schema.json", plan), ("manifest.schema.json", manifest)):
        schema = json.loads((schemas / filename).read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(document)


def test_plan_schema_rejects_cross_platform_path_escape() -> None:
    schema = json.loads((ROOT / "schemas" / "plan.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    base = {
        "schema_version": "1.0",
        "run_id": "run-test",
        "created_at": "2026-08-03T00:00:00+00:00",
        "workspace_root": "<SIMS4_WORKSPACE>",
        "dry_run": True,
        "profile": "neutral",
        "operations": [
            {
                "operation_id": "12345678-1234-5678-9234-567812345678",
                "action": "install",
                "source": "staging/direct/Fictional.package",
                "destination": "Fictional.package",
                "reason": "new_file",
                "evidence": {},
                "requires_review": False,
                "source_sha256": "0" * 64,
                "target_sha256": None,
            }
        ],
    }

    for unsafe in (
        "../escape.package",
        "..\\escape.package",
        "C:\\escape.package",
        "\\\\server\\file",
    ):
        document = json.loads(json.dumps(base))
        document["operations"][0]["destination"] = unsafe
        assert not validator.is_valid(document), unsafe
