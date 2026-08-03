from __future__ import annotations

import csv
import html
import io
import json
import os
import uuid
from collections import defaultdict
from pathlib import Path

from .localization import Translator
from .models import Finding, ScanSnapshot
from .privacy import PathRedactor

REPORT_FILENAMES = (
    "report.html",
    "inventory.csv",
    "report.json",
    "report.txt",
    "AI_HANDOFF.md",
)


def _atomic_write_text(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite report: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _finding_title(finding: Finding, translator: Translator) -> str:
    return translator.text(f"finding.{finding.code.value}")


def _summary_rows(snapshot: ScanSnapshot, translator: Translator) -> list[tuple[str, int]]:
    summary = snapshot.summary
    return [
        (translator.text("summary.files_total"), summary.files_total),
        (translator.text("summary.package_files"), summary.package_files),
        (translator.text("summary.ts4script_files"), summary.ts4script_files),
        (translator.text("summary.archives"), summary.archives),
        (translator.text("summary.exact_duplicate_groups"), summary.exact_duplicate_groups),
        (translator.text("summary.name_conflict_groups"), summary.name_conflict_groups),
        (translator.text("summary.script_depth_issues"), summary.script_depth_issues),
        (translator.text("summary.root_loose_files"), summary.root_loose_files),
        (translator.text("summary.empty_directories"), summary.empty_directories),
        (translator.text("summary.unsafe_symlinks"), summary.unsafe_symlinks),
    ]


def _render_json(snapshot: ScanSnapshot) -> str:
    return json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2) + "\n"


def _render_csv(snapshot: ScanSnapshot, translator: Translator) -> str:
    findings_by_path: dict[str, list[str]] = defaultdict(list)
    for finding in snapshot.findings:
        for path in finding.paths:
            findings_by_path[path].append(finding.code.value)

    output = io.StringIO(newline="")
    headers = [
        translator.text("column.relative_path"),
        translator.text("column.name"),
        translator.text("column.kind"),
        translator.text("column.size"),
        translator.text("column.sha256"),
        translator.text("column.modified_ns"),
        translator.text("column.folder_depth"),
        translator.text("column.findings"),
    ]
    writer = csv.writer(output)
    writer.writerow(headers)
    for record in snapshot.files:
        writer.writerow(
            [
                record.relative_path,
                record.name,
                record.kind.value,
                record.size,
                record.sha256 or "",
                record.modified_ns,
                record.folder_depth,
                " | ".join(findings_by_path.get(record.relative_path, [])),
            ]
        )
    return output.getvalue()


def _render_text(snapshot: ScanSnapshot, translator: Translator) -> str:
    lines = [
        translator.text("report.title"),
        "=" * len(translator.text("report.title")),
        f"{translator.text('report.run_id')}: {snapshot.run_id}",
        f"{translator.text('report.created_at')}: {snapshot.created_at}",
        f"{translator.text('report.mods_root')}: {snapshot.mods_root}",
        "",
        translator.text("report.summary"),
    ]
    lines.extend(f"- {label}: {value}" for label, value in _summary_rows(snapshot, translator))
    lines.extend(["", translator.text("report.findings")])
    if not snapshot.findings:
        lines.append(translator.text("report.no_findings"))
    for finding in snapshot.findings:
        paths = ", ".join(finding.paths) or translator.text("report.not_applicable")
        evidence = json.dumps(finding.evidence, ensure_ascii=False, sort_keys=True)
        lines.extend(
            [
                f"- [{finding.severity.value}] {_finding_title(finding, translator)}",
                f"  {translator.text('report.paths')}: {paths}",
                f"  {translator.text('report.evidence')}: {evidence}",
            ]
        )
    return "\n".join(lines) + "\n"


def _render_html(snapshot: ScanSnapshot, translator: Translator) -> str:
    summary_cards = "".join(
        f"<div class=\"card\"><span>{html.escape(label)}</span><strong>{value}</strong></div>"
        for label, value in _summary_rows(snapshot, translator)
    )
    finding_rows = []
    for finding in snapshot.findings:
        paths = "<br>".join(html.escape(path) for path in finding.paths) or "—"
        evidence = html.escape(json.dumps(finding.evidence, ensure_ascii=False, sort_keys=True))
        finding_rows.append(
            "<tr>"
            f"<td>{html.escape(finding.severity.value)}</td>"
            f"<td>{html.escape(_finding_title(finding, translator))}</td>"
            f"<td>{paths}</td>"
            f"<td><code>{evidence}</code></td>"
            "</tr>"
        )
    if not finding_rows:
        finding_rows.append(
            f"<tr><td colspan=\"4\">{html.escape(translator.text('report.no_findings'))}</td></tr>"
        )

    inventory_rows = "".join(
        "<tr>"
        f"<td>{html.escape(record.relative_path)}</td>"
        f"<td>{html.escape(record.kind.value)}</td>"
        f"<td>{record.size}</td>"
        f"<td><code>{html.escape(record.sha256 or '—')}</code></td>"
        "</tr>"
        for record in snapshot.files
    )
    return f"""<!doctype html>
<html lang="{html.escape(translator.language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(translator.text('report.title'))}</title>
<style>
body{{font:15px system-ui,sans-serif;margin:0;background:#f4f6f8;color:#17202a}}
main{{max-width:1200px;margin:32px auto;background:#fff;padding:28px;border-radius:14px}}
.meta{{color:#59636e}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}
.card{{background:#eef3f7;padding:14px;border-radius:9px}}.card span,.card strong{{display:block}}.card strong{{font-size:24px}}
.table{{overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid #dce2e7;padding:9px;text-align:left;vertical-align:top}}
th{{background:#20364d;color:#fff}}code{{font-size:12px;overflow-wrap:anywhere}}
</style>
</head>
<body><main>
<h1>{html.escape(translator.text('report.title'))}</h1>
<p class="meta">{html.escape(translator.text('report.run_id'))}: {html.escape(snapshot.run_id)}<br>
{html.escape(translator.text('report.created_at'))}: {html.escape(snapshot.created_at)}<br>
{html.escape(translator.text('report.mods_root'))}: {html.escape(snapshot.mods_root)}</p>
<h2>{html.escape(translator.text('report.summary'))}</h2><div class="cards">{summary_cards}</div>
<h2>{html.escape(translator.text('report.findings'))}</h2><div class="table"><table><thead><tr>
<th>{html.escape(translator.text('column.severity'))}</th><th>{html.escape(translator.text('column.finding'))}</th>
<th>{html.escape(translator.text('column.relative_path'))}</th><th>{html.escape(translator.text('report.evidence'))}</th>
</tr></thead><tbody>{''.join(finding_rows)}</tbody></table></div>
<h2>{html.escape(translator.text('report.inventory'))}</h2><div class="table"><table><thead><tr>
<th>{html.escape(translator.text('column.relative_path'))}</th><th>{html.escape(translator.text('column.kind'))}</th>
<th>{html.escape(translator.text('column.size'))}</th><th>{html.escape(translator.text('column.sha256'))}</th>
</tr></thead><tbody>{inventory_rows}</tbody></table></div>
</main></body></html>
"""


def _render_ai_handoff(snapshot: ScanSnapshot, translator: Translator) -> str:
    lines = [
        f"# {translator.text('ai.title')}",
        "",
        translator.text("ai.privacy_notice"),
        "",
        f"- {translator.text('report.run_id')}: `{snapshot.run_id}`",
        f"- {translator.text('report.mods_root')}: `{snapshot.mods_root}`",
        f"- {translator.text('summary.package_files')}: {snapshot.summary.package_files}",
        f"- {translator.text('summary.ts4script_files')}: {snapshot.summary.ts4script_files}",
        "",
        f"## {translator.text('report.findings')}",
        "",
    ]
    if not snapshot.findings:
        lines.append(translator.text("report.no_findings"))
    for finding in snapshot.findings:
        paths = ", ".join(f"`{path}`" for path in finding.paths) or "—"
        evidence = json.dumps(finding.evidence, ensure_ascii=False, sort_keys=True)
        lines.append(
            f"- **{_finding_title(finding, translator)}** ({finding.severity.value}): "
            f"{paths}; {translator.text('report.evidence')}: `{evidence}`"
        )
    lines.extend(
        [
            "",
            f"## {translator.text('ai.rules_title')}",
            "",
            translator.text("ai.rules"),
        ]
    )
    return "\n".join(lines) + "\n"


def write_scan_reports(
    snapshot: ScanSnapshot,
    output_directory: Path,
    *,
    translator: Translator,
    redactor: PathRedactor,
) -> dict[str, Path]:
    if not output_directory.is_dir():
        raise NotADirectoryError(f"Report directory does not exist: {output_directory}")
    rendered = {
        "report.html": _render_html(snapshot, translator),
        "inventory.csv": _render_csv(snapshot, translator),
        "report.json": _render_json(snapshot),
        "report.txt": _render_text(snapshot, translator),
        "AI_HANDOFF.md": _render_ai_handoff(snapshot, translator),
    }
    written: dict[str, Path] = {}
    for filename in REPORT_FILENAMES:
        destination = output_directory / filename
        _atomic_write_text(destination, redactor.redact(rendered[filename]))
        written[filename] = destination
    return written
