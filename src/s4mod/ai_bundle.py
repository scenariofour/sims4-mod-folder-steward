from __future__ import annotations

import zipfile
from pathlib import Path

from .localization import normalize_locale

AI_FILES = (
    "AI_HANDOFF.md",
    "report.html",
    "report.json",
    "report.txt",
    "inventory.csv",
)


def ai_review_prompt(language: str) -> str:
    language = normalize_locale(language)
    if language == "zh-CN":
        return (
            "请检查这个匿名化 Sims 4 Mods 报告，必要时使用你自己的浏览工具调查候选更新。"
            "请说明证据、来源链接和不确定性，不要生成可直接执行的删除或覆盖命令。"
            "本地工具会重新验证所有建议，并由用户确认后才执行。"
        )
    return (
        "Review this anonymized Sims 4 Mods report. If needed, use your own browsing tools to "
        "investigate candidate updates. Explain evidence, source links, and uncertainty. Do not "
        "produce directly executable delete or overwrite commands. The local tool will revalidate "
        "every suggestion and require user approval before applying it."
    )


def export_ai_check_bundle(
    run_directory: Path,
    destination: Path,
    *,
    language: str,
) -> Path:
    if destination.suffix.casefold() != ".zip":
        destination = destination.with_suffix(".zip")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"AI check bundle already exists: {destination}")
    sources: list[Path] = []
    for filename in AI_FILES:
        source = run_directory / filename
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError(f"AI bundle source is missing or unsafe: {filename}")
        sources.append(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination,
        "x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as bundle:
        for source in sources:
            bundle.write(source, arcname=source.name)
        bundle.writestr("AI_PROMPT.txt", ai_review_prompt(language))
    return destination
