from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    gemini_api_key: str
    gemini_model: str
    coalescence_api_key: str
    coalescence_base_url: str
    transparency_github_repo_url: str | None
    transparency_github_blob_base_url: str | None
    logs_dir: Path
    max_paper_chars: int
    max_existing_comments: int
    reply_limit: int
    verdict_confidence_threshold: float
    comment_confidence_threshold: float
    enable_external_evidence_loop: bool
    max_research_rounds: int
    external_search_results: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        coalescence_api_key = os.getenv("COALESCENCE_API_KEY", "").strip()
        if not gemini_api_key:
            raise ValueError("Missing GEMINI_API_KEY in environment.")
        if not coalescence_api_key:
            raise ValueError("Missing COALESCENCE_API_KEY in environment.")

        return cls(
            gemini_api_key=gemini_api_key,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview").strip(),
            coalescence_api_key=coalescence_api_key,
            coalescence_base_url=os.getenv(
                "COALESCENCE_BASE_URL", "https://coale.science/api/v1"
            ).rstrip("/"),
            transparency_github_repo_url=os.getenv("TRANSPARENCY_GITHUB_REPO_URL"),
            transparency_github_blob_base_url=os.getenv(
                "TRANSPARENCY_GITHUB_BLOB_BASE_URL"
            ),
            logs_dir=Path("logs"),
            max_paper_chars=int(os.getenv("MAX_PAPER_CHARS", "180000")),
            max_existing_comments=int(os.getenv("MAX_EXISTING_COMMENTS", "20")),
            reply_limit=int(os.getenv("REPLY_LIMIT", "2")),
            verdict_confidence_threshold=float(
                os.getenv("VERDICT_CONFIDENCE_THRESHOLD", "0.82")
            ),
            comment_confidence_threshold=float(
                os.getenv("COMMENT_CONFIDENCE_THRESHOLD", "0.55")
            ),
            enable_external_evidence_loop=os.getenv(
                "ENABLE_EXTERNAL_EVIDENCE_LOOP", "true"
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            max_research_rounds=int(os.getenv("MAX_RESEARCH_ROUNDS", "2")),
            external_search_results=int(os.getenv("EXTERNAL_SEARCH_RESULTS", "5")),
        )
