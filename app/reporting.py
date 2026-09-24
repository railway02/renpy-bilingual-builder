"""Failure diagnostics are separate artifacts, never a successful output package."""

import csv
import json
from pathlib import Path
import uuid

from tools.build_bilingual import NoReliableDialogueError


def save_failure_report(error: NoReliableDialogueError, requested: Path, output: Path) -> Path:
    report = requested.with_name(f"{requested.stem}_failed_{uuid.uuid4().hex}.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    data = dict(error.summary, status="failed", error=str(error),
                destination=str(output.resolve()), diagnostics_csv=str(report.with_suffix(".csv")))
    provenance = {record["path"]: record for record in data.get("input_manifest", {}).get("files", [])}
    diagnostics = []
    for diagnostic in data.get("diagnostics", []):
        record = provenance.get(diagnostic["file"], {})
        diagnostics.append(dict(diagnostic, source=record.get("source", ""), member=record.get("member", "")))
    data["diagnostics"] = diagnostics
    with report.with_suffix(".csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["file", "line", "block_id", "reason", "action", "source", "member"])
        writer.writeheader()
        writer.writerows(diagnostics)
    with report.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    error.report_path = report
    return report
