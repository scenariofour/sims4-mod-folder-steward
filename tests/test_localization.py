from __future__ import annotations

import json
from pathlib import Path

from s4mod.localization import load_folder_profile

ROOT = Path(__file__).parents[1]


def test_locale_key_sets_match() -> None:
    en = json.loads((ROOT / "locales/en.json").read_text(encoding="utf-8"))
    zh = json.loads((ROOT / "locales/zh-CN.json").read_text(encoding="utf-8"))
    assert set(en) == set(zh)


def test_localized_profiles_use_same_stable_category_ids() -> None:
    en = load_folder_profile("en")
    zh = load_folder_profile("zh-CN")
    neutral = load_folder_profile("neutral")
    assert set(en["categories"]) == set(zh["categories"])
    assert neutral["preserve_existing_structure"] is True
    assert neutral["create_missing_categories"] is False
