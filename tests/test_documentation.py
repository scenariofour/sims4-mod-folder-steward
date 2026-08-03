from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def test_local_markdown_links_resolve() -> None:
    missing: list[str] = []
    for document in ROOT.rglob("*.md"):
        if any(part.startswith(".") for part in document.relative_to(ROOT).parts):
            continue
        for raw_target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve(strict=False)
            if not resolved.exists():
                missing.append(f"{document.relative_to(ROOT)} -> {raw_target}")
    assert not missing, "\n".join(missing)


def test_packaging_spec_is_valid_python() -> None:
    source = (ROOT / "packaging" / "s4mod-steward.spec").read_text(encoding="utf-8")
    compile(source, "s4mod-steward.spec", "exec")
