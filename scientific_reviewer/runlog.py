from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RunLogger:
    root: Path
    github_blob_base_url: str | None = None

    @classmethod
    def create(
        cls, logs_dir: Path, paper_id: str, github_blob_base_url: str | None
    ) -> "RunLogger":
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        root = (logs_dir / "runs" / f"{timestamp}-{paper_id}").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return cls(root=root, github_blob_base_url=github_blob_base_url)

    def write_json(self, relative_path: str, payload: Any) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        return path

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def append_jsonl(self, relative_path: str, payload: Any) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return path

    def log_event(self, event_type: str, **payload: Any) -> Path:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            **payload,
        }
        return self.append_jsonl("events.jsonl", event)

    def console(self, message: str) -> None:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[{timestamp}] {message}", flush=True)

    def github_url(self, file_path: Path) -> str | None:
        if not self.github_blob_base_url:
            return None
        relative = file_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        return f"{self.github_blob_base_url.rstrip('/')}/{relative}"
