from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_LOCALES = ("en", "zh-CN")


def _resource_root(name: str) -> Path:
    packaged = Path(__file__).resolve().parent / name
    if packaged.is_dir():
        return packaged
    repository = Path(__file__).resolve().parents[2] / name
    if repository.is_dir():
        return repository
    raise FileNotFoundError(f"Bundled resource directory is missing: {name}")


def normalize_locale(language: str) -> str:
    normalized = language.strip().replace("_", "-").casefold()
    if normalized == "en" or normalized.startswith("en-"):
        return "en"
    if normalized in {"zh", "zh-cn", "zh-hans"}:
        return "zh-CN"
    raise ValueError(f"Unsupported language: {language}")


def load_locale(locale_path: Path) -> dict[str, Any]:
    with locale_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise ValueError("Locale root must be an object with string keys.")
    return data


@dataclass(frozen=True, slots=True)
class Translator:
    language: str
    messages: dict[str, Any]

    @classmethod
    def load(cls, language: str) -> Translator:
        language = normalize_locale(language)
        return cls(language, load_locale(_resource_root("locales") / f"{language}.json"))

    def text(self, key: str, **values: object) -> str:
        message = self.messages.get(key)
        if not isinstance(message, str):
            raise KeyError(f"Missing locale key '{key}' for {self.language}")
        return message.format(**values)


def load_folder_profile(profile: str) -> dict[str, Any]:
    normalized = "zh-CN" if profile.casefold() in {"zh", "zh-cn"} else profile.casefold()
    filename = {"en": "en.yml", "zh-CN": "zh-CN.yml", "neutral": "neutral.yml"}.get(normalized)
    if filename is None:
        raise ValueError(f"Unsupported folder profile: {profile}")
    with (_resource_root("folder_profiles") / filename).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise TypeError("Folder profile root must be an object.")
    return data
