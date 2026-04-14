from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SchedulerState:
    path: Path
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "SchedulerState":
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = {"papers": {}}
        return cls(path=path, payload=payload)

    def has_reviewed(self, paper_id: str) -> bool:
        return paper_id in self.payload.setdefault("papers", {})

    def mark_reviewed(self, paper_id: str, summary: dict[str, Any]) -> None:
        self.payload.setdefault("papers", {})[paper_id] = {
            "updated_at": datetime.now(UTC).isoformat(),
            "confidence": summary.get("confidence"),
            "verdict_ready": summary.get("verdict_ready"),
            "needs_more_discussion": summary.get("needs_more_discussion"),
            "score": summary.get("score"),
            "run_dir": summary.get("run_dir"),
            "actions": summary.get("actions"),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
