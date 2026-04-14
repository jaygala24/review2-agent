from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scientific_reviewer.coalescence import CoalescenceClient
from scientific_reviewer.config import Settings
from scientific_reviewer.gemini import GeminiClient
from scientific_reviewer.paper import download_pdf, extract_pdf_text
from scientific_reviewer.prompts import (
    SYSTEM_PROMPT,
    adjudication_prompt,
    paper_map_prompt,
    planning_prompt,
    specialist_prompt,
)
from scientific_reviewer.runlog import RunLogger


@dataclass(slots=True)
class ReviewOptions:
    post_comment: bool = False
    engage_discussion: bool = False
    post_verdict: bool = False


class ScientificReviewAgent:
    def __init__(self, settings: Settings):
        self.settings = settings

    def sync_profile(self) -> dict[str, Any]:
        logger = RunLogger.create(
            self.settings.logs_dir,
            paper_id="profile-sync",
            github_blob_base_url=self.settings.transparency_github_blob_base_url,
        )
        client = CoalescenceClient(
            self.settings.coalescence_base_url,
            self.settings.coalescence_api_key,
            logger=logger,
        )
        if not self.settings.transparency_github_repo_url:
            raise ValueError(
                "Missing TRANSPARENCY_GITHUB_REPO_URL; required for profile sync."
            )
        profile = client.update_my_profile(
            github_repo=self.settings.transparency_github_repo_url,
            description=(
                "Hierarchical scientific validity reviewer using Gemini with "
                "evidence-grounded specialist stages and transparent audit logs."
            ),
        )
        logger.write_json("profile.json", profile)
        return profile

    def review(self, paper_id: str, options: ReviewOptions) -> dict[str, Any]:
        if options.post_verdict:
            options.post_comment = True
            options.engage_discussion = True

        logger = RunLogger.create(
            self.settings.logs_dir,
            paper_id=paper_id,
            github_blob_base_url=self.settings.transparency_github_blob_base_url,
        )
        platform = CoalescenceClient(
            self.settings.coalescence_base_url,
            self.settings.coalescence_api_key,
            logger=logger,
        )
        llm = GeminiClient(
            self.settings.gemini_api_key,
            self.settings.gemini_model,
            logger=logger,
        )

        profile = platform.get_my_profile()
        paper = platform.get_paper(paper_id)
        revisions = platform.get_paper_revisions(paper_id)
        comments = platform.get_comments(paper_id)
        verdicts = platform.get_verdicts(paper_id)

        logger.write_json("paper/profile.json", profile)
        logger.write_json("paper/paper.json", paper)
        logger.write_json("paper/revisions.json", revisions)
        logger.write_json("paper/comments.json", comments)
        logger.write_json("paper/verdicts.json", verdicts)

        pdf_url = paper.get("pdf_url") or paper.get("latest_revision", {}).get(
            "pdf_url"
        )
        if not pdf_url:
            raise ValueError(f"Paper {paper_id} does not expose a pdf_url.")

        pdf_bytes = download_pdf(pdf_url)
        paper_text = extract_pdf_text(pdf_bytes)
        if not paper_text.strip():
            raise ValueError("PDF text extraction returned no usable content.")
        truncated_text = paper_text[: self.settings.max_paper_chars]
        logger.write_text("paper/extracted_text.txt", truncated_text)

        filtered_comments = self._select_comments(comments)
        paper_map = llm.generate_json(
            system_instruction=SYSTEM_PROMPT,
            prompt=paper_map_prompt(
                paper=paper,
                revisions=revisions,
                paper_text=truncated_text,
            ),
        )
        logger.write_json("analysis/paper_map.json", paper_map)

        planning = llm.generate_json(
            system_instruction=SYSTEM_PROMPT,
            prompt=planning_prompt(
                paper=paper,
                paper_map=paper_map,
                comments=filtered_comments,
            ),
        )
        logger.write_json("analysis/planning.json", planning)

        specialist_outputs: list[dict[str, Any]] = []
        for specialist in planning.get("specialists", [])[:4]:
            result = llm.generate_json(
                system_instruction=SYSTEM_PROMPT,
                prompt=specialist_prompt(
                    paper=paper,
                    paper_map=paper_map,
                    specialist=specialist,
                ),
            )
            specialist_outputs.append(result)
            safe_name = specialist.get("name", "specialist")
            logger.write_json(f"analysis/specialists/{safe_name}.json", result)

        adjudication = llm.generate_json(
            system_instruction=SYSTEM_PROMPT,
            prompt=adjudication_prompt(
                paper=paper,
                paper_map=paper_map,
                planning=planning,
                specialists=specialist_outputs,
                comments=filtered_comments,
                existing_verdicts=verdicts,
            ),
        )
        logger.write_json("analysis/adjudication.json", adjudication)

        main_comment = self._build_main_comment(paper, paper_map, adjudication)
        main_comment_path = logger.write_text("outputs/main_comment.md", main_comment)
        comment_support = self._build_comment_support(
            paper, paper_map, planning, specialist_outputs, adjudication
        )
        comment_support_path = logger.write_text(
            "outputs/main_comment_support.md", comment_support
        )

        replies = self._build_replies(filtered_comments, adjudication)
        reply_paths: dict[str, Path] = {}
        for index, reply in enumerate(replies, start=1):
            reply_paths[reply["comment_id"]] = logger.write_text(
                f"outputs/reply_{index}_{reply['comment_id']}.md", reply["content"]
            )

        verdict_markdown = self._build_verdict(paper, adjudication)
        verdict_path = logger.write_text("outputs/verdict.md", verdict_markdown)
        verdict_support_path = logger.write_text(
            "outputs/verdict_support.md",
            self._build_verdict_support(
                paper, paper_map, specialist_outputs, adjudication
            ),
        )

        actions: dict[str, Any] = {
            "main_comment_posted": False,
            "reply_count_posted": 0,
            "vote_count_cast": 0,
            "verdict_posted": False,
        }

        confidence = float(adjudication.get("confidence", 0.0))
        can_post_comment = bool(adjudication.get("main_comment_should_post", True)) or (
            confidence >= self.settings.comment_confidence_threshold
        )

        if options.post_comment and can_post_comment:
            comment_url = logger.github_url(comment_support_path)
            if not comment_url:
                raise ValueError(
                    "Missing TRANSPARENCY_GITHUB_BLOB_BASE_URL; required for live posting."
                )
            posted_comment = platform.post_comment(
                paper_id=paper_id,
                content_markdown=main_comment,
                github_file_url=comment_url,
            )
            actions["main_comment_posted"] = True
            actions["main_comment_id"] = posted_comment.get("id")
            logger.write_json("posted/main_comment.json", posted_comment)

        if options.engage_discussion:
            for reply in replies[: self.settings.reply_limit]:
                reply_url = logger.github_url(reply_paths[reply["comment_id"]])
                if not reply_url:
                    raise ValueError(
                        "Missing TRANSPARENCY_GITHUB_BLOB_BASE_URL; required for live posting."
                    )
                posted_reply = platform.post_comment(
                    paper_id=paper_id,
                    content_markdown=reply["content"],
                    github_file_url=reply_url,
                    parent_id=reply["comment_id"],
                )
                actions["reply_count_posted"] += 1
                logger.write_json(
                    f"posted/reply_{reply['comment_id']}.json", posted_reply
                )

            for vote in adjudication.get("vote_plan", []):
                target_comment = self._find_comment(
                    filtered_comments, vote.get("comment_id")
                )
                if not target_comment:
                    continue
                if target_comment.get("author_id") == profile.get("id"):
                    continue
                try:
                    platform.cast_vote(
                        target_id=vote["comment_id"],
                        target_type="COMMENT",
                        vote_value=int(vote["vote_value"]),
                    )
                    actions["vote_count_cast"] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.write_json(
                        f"posted/vote_{vote['comment_id']}_error.json",
                        {"error": str(exc), "vote": vote},
                    )

        if (
            options.post_verdict
            and adjudication.get("verdict_ready")
            and confidence >= self.settings.verdict_confidence_threshold
            and actions["vote_count_cast"] > 0
            and actions["main_comment_posted"]
        ):
            verdict_url = logger.github_url(verdict_support_path)
            if not verdict_url:
                raise ValueError(
                    "Missing TRANSPARENCY_GITHUB_BLOB_BASE_URL; required for live posting."
                )
            posted_verdict = platform.post_verdict(
                paper_id=paper_id,
                content_markdown=verdict_markdown,
                score=float(adjudication.get("score", 0.0)),
                github_file_url=verdict_url,
            )
            actions["verdict_posted"] = True
            logger.write_json("posted/verdict.json", posted_verdict)

        summary = {
            "paper_id": paper_id,
            "title": paper.get("title"),
            "confidence": confidence,
            "score": adjudication.get("score"),
            "verdict_ready": adjudication.get("verdict_ready"),
            "run_dir": str(logger.root),
            "main_comment_path": str(main_comment_path),
            "verdict_path": str(verdict_path),
            "actions": actions,
            "escalation_flags": adjudication.get("escalation_flags", []),
        }
        logger.write_json("summary.json", summary)
        return summary

    def _select_comments(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sorted_comments = sorted(
            comments,
            key=lambda item: (
                item.get("parent_id") is not None,
                -(item.get("net_score") or 0),
                item.get("created_at") or "",
            ),
        )
        return sorted_comments[: self.settings.max_existing_comments]

    def _find_comment(
        self, comments: list[dict[str, Any]], comment_id: str | None
    ) -> dict[str, Any] | None:
        for comment in comments:
            if comment.get("id") == comment_id:
                return comment
        return None

    def _build_main_comment(
        self,
        paper: dict[str, Any],
        paper_map: dict[str, Any],
        adjudication: dict[str, Any],
    ) -> str:
        strengths = (
            "\n".join(
                f"- {item}" for item in adjudication.get("consensus_strengths", [])[:4]
            )
            or "- No strong manuscript-grounded strengths were confidently established."
        )
        concerns = (
            "\n".join(
                f"- [{item.get('severity', 'medium')}] {item.get('point')}: {item.get('rationale')}"
                for item in adjudication.get("consensus_concerns", [])[:5]
            )
            or "- No decisive technical concerns were identified."
        )
        questions = (
            "\n".join(
                f"- {item}"
                for item in adjudication.get("questions_for_authors", [])[:4]
            )
            or "- No additional author questions."
        )
        return (
            f"## Summary\n{paper_map.get('one_sentence_summary', paper.get('abstract', ''))}\n\n"
            f"## Strengths\n{strengths}\n\n"
            f"## Main Technical Concerns\n{concerns}\n\n"
            f"## Questions For The Authors\n{questions}\n\n"
            f"## Overall Assessment\n{adjudication.get('overall_assessment', '')}\n\n"
            f"Confidence: `{float(adjudication.get('confidence', 0.0)):.2f}`\n"
        )

    def _build_comment_support(
        self,
        paper: dict[str, Any],
        paper_map: dict[str, Any],
        planning: dict[str, Any],
        specialist_outputs: list[dict[str, Any]],
        adjudication: dict[str, Any],
    ) -> str:
        return (
            f"# Comment Support Log\n\n"
            f"Paper: `{paper.get('id')}`\n\n"
            f"Title: {paper.get('title')}\n\n"
            f"## Review Focus\n{planning.get('review_focus', '')}\n\n"
            f"## Caution Flags\n"
            + "\n".join(f"- {flag}" for flag in planning.get("caution_flags", []))
            + "\n\n## Paper Map\n```json\n"
            + json.dumps(paper_map, indent=2, ensure_ascii=True)
            + "\n```\n\n## Specialist Outputs\n```json\n"
            + json.dumps(specialist_outputs, indent=2, ensure_ascii=True)
            + "\n```\n\n## Adjudication\n```json\n"
            + json.dumps(adjudication, indent=2, ensure_ascii=True)
            + "\n```\n"
        )

    def _build_replies(
        self, comments: list[dict[str, Any]], adjudication: dict[str, Any]
    ) -> list[dict[str, str]]:
        replies: list[dict[str, str]] = []
        for plan in adjudication.get("reply_plan", []):
            target = self._find_comment(comments, plan.get("comment_id"))
            if not target:
                continue
            stance = plan.get("stance", "agree")
            prefix = (
                "I agree with this rationale"
                if stance == "agree"
                else "I disagree with this rationale"
            )
            replies.append(
                {
                    "comment_id": target["id"],
                    "content": (
                        f"{prefix} on the current evidence. {plan.get('rationale', '')}\n\n"
                        f"Grounding: {plan.get('evidence', '')}"
                    ),
                }
            )
        return replies

    def _build_verdict(
        self, paper: dict[str, Any], adjudication: dict[str, Any]
    ) -> str:
        score = float(adjudication.get("score", 0.0))
        return (
            f"## Verdict\n{adjudication.get('overall_assessment', '')}\n\n"
            f"## Score Rationale\n{adjudication.get('verdict_rationale', '')}\n\n"
            f"Score: `{score:.1f}/10`\n"
            f"Confidence: `{float(adjudication.get('confidence', 0.0)):.2f}`\n\n"
            f"Paper: **{paper.get('title')}**\n"
        )

    def _build_verdict_support(
        self,
        paper: dict[str, Any],
        paper_map: dict[str, Any],
        specialist_outputs: list[dict[str, Any]],
        adjudication: dict[str, Any],
    ) -> str:
        return (
            f"# Verdict Support Log\n\n"
            f"Paper: `{paper.get('id')}`\n\n"
            f"## Structured Evidence\n```json\n"
            + json.dumps(paper_map, indent=2, ensure_ascii=True)
            + "\n```\n\n## Specialist Outputs\n```json\n"
            + json.dumps(specialist_outputs, indent=2, ensure_ascii=True)
            + "\n```\n\n## Final Adjudication\n```json\n"
            + json.dumps(adjudication, indent=2, ensure_ascii=True)
            + "\n```\n"
        )
