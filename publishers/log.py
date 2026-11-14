"""Publishing log (JSONL) and report. Everything is redacted before it is written."""

from __future__ import annotations

import json
from pathlib import Path

from .models import now
from .redact import redact


class PublishLog:
    def __init__(self, project_root: Path):
        self.file = Path(project_root) / "publish" / "log.jsonl"

    def write(self, event: str, job_id: str | None = None, **data) -> dict:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        entry = redact({"time": now(), "event": event, "job": job_id, **data})
        with open(self.file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def read(self, job_id: str | None = None, limit: int | None = None) -> list[dict]:
        if not self.file.exists():
            return []
        rows = [json.loads(line) for line in self.file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if job_id:
            rows = [r for r in rows if r.get("job") == job_id]
        return rows[-limit:] if limit else rows


def report_markdown(jobs, log_rows) -> str:
    icon = {"pending": "⏳", "validated": "🔎", "approved": "✅", "uploading": "⬆️", "processing": "⚙️",
            "completed": "🎉", "failed": "❌"}
    out = ["# Publishing report", "", "> Phase 6.1: sirf framework. Koi asal upload nahi hota.", "",
           "| Job | Platform | Status | Privacy | Validation | Approval |", "|---|---|---|---|---|---|"]
    for j in jobs:
        v = j.validation or {}
        vtxt = ("✅" if v.get("ok") else "❌") + f" {len(v.get('errors', []))} errors / {len(v.get('warnings', []))} warnings" if v else "—"
        a = "✅ " + j.approval.get("time", "") if j.approval else "—"
        out.append(f"| `{j.id}` | {j.platform} | {icon.get(j.status, '')} {j.status} | {j.privacy} | {vtxt} | {a} |")
    out += ["", "## Aakhri log entries", "", "```"]
    out += [json.dumps(redact(r), ensure_ascii=False) for r in log_rows[-20:]]
    out += ["```", ""]
    return "\n".join(out)
