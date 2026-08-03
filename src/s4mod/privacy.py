from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PathRedactor:
    replacements: tuple[tuple[str, str], ...]
    usernames: tuple[str, ...]

    @classmethod
    def for_run(
        cls,
        *,
        mods_root: Path,
        workspace_root: Path,
        run_root: Path,
        home: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> PathRedactor:
        home = (home or Path.home()).expanduser().resolve(strict=False)
        environ = environ or os.environ
        mappings = {
            str(run_root.resolve(strict=False)): "<RUN_FOLDER>",
            str(mods_root.resolve(strict=False)): "<MODS_FOLDER>",
            str(workspace_root.resolve(strict=False)): "<SIMS4_WORKSPACE>",
            str(home): "<HOME>",
        }
        replacements = tuple(sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True))
        usernames = {
            value
            for value in (home.name, environ.get("USER"), environ.get("USERNAME"))
            if value and len(value) >= 3
        }
        return cls(replacements=replacements, usernames=tuple(sorted(usernames, key=len, reverse=True)))

    def redact(self, value: str) -> str:
        result = value
        for raw, placeholder in self.replacements:
            variants = {raw, raw.replace("\\", "/"), raw.replace("/", "\\")}
            for variant in sorted(variants, key=len, reverse=True):
                result = re.sub(re.escape(variant), placeholder, result, flags=re.IGNORECASE)
        for username in self.usernames:
            result = re.sub(
                rf"(?<![\w.-]){re.escape(username)}(?![\w.-])",
                "<USER>",
                result,
                flags=re.IGNORECASE,
            )
        return result

    def contains_private_value(self, value: str) -> bool:
        return self.redact(value) != value
