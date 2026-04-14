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
    reassessment_prompt,
    research_plan_prompt,
    specialist_prompt,
)
from scientific_reviewer.research import ExternalEvidenceCollector
from scientific_reviewer.runlog import RunLogger
from scientific_reviewer.state import SchedulerState


@dataclass(slots=True)
class ReviewOptions:
    post_comment: bool = False
    engage_discussion: bool = False
    post_verdict: bool = False


class ScientificReviewAgent:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _paper_label(self, paper: dict[str, Any], paper_id: str) -> str:
        title = str(paper.get("title") or "").strip()
        return f"{title} ({paper_id})" if title else paper_id

    def _settings_snapshot(self) -> dict[str, Any]:
        return {
            "gemini_model": self.settings.gemini_model,
            "coalescence_base_url": self.settings.coalescence_base_url,
            "semantic_scholar_api_key_configured": bool(
                self.settings.semantic_scholar_api_key
            ),
            "transparency_github_repo_url": self.settings.transparency_github_repo_url,
            "transparency_github_blob_base_url": self.settings.transparency_github_blob_base_url,
            "max_paper_chars": self.settings.max_paper_chars,
            "max_existing_comments": self.settings.max_existing_comments,
            "reply_limit": self.settings.reply_limit,
            "verdict_confidence_threshold": self.settings.verdict_confidence_threshold,
            "comment_confidence_threshold": self.settings.comment_confidence_threshold,
            "enable_external_evidence_loop": self.settings.enable_external_evidence_loop,
            "max_research_rounds": self.settings.max_research_rounds,
            "external_search_results": self.settings.external_search_results,
        }

    def sync_profile(self) -> dict[str, Any]:
        logger = RunLogger.create(
            self.settings.logs_dir,
            paper_id="profile-sync",
            github_blob_base_url=self.settings.transparency_github_blob_base_url,
        )
        logger.write_json("session/settings.json", self._settings_snapshot())
        logger.log_event("session_start", command="sync-profile")
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
                "evidence-grounded specialist stages, discussion-first escalation, "
                "and transparent audit logs."
            ),
        )
        logger.write_json("profile.json", profile)
        logger.log_event("session_complete", command="sync-profile")
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
        logger.write_json(
            "session/options.json",
            {
                "paper_id": paper_id,
                "post_comment": options.post_comment,
                "engage_discussion": options.engage_discussion,
                "post_verdict": options.post_verdict,
            },
        )
        logger.write_json("session/settings.json", self._settings_snapshot())
        logger.log_event(
            "session_start",
            command="review",
            paper_id=paper_id,
            options={
                "post_comment": options.post_comment,
                "engage_discussion": options.engage_discussion,
                "post_verdict": options.post_verdict,
            },
        )
        logger.console(f"Starting review for paper {paper_id}")
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
        logger.log_event(
            "paper_context_loaded",
            paper_id=paper_id,
            comment_count=len(comments),
            verdict_count=len(verdicts),
            revision_count=len(revisions),
        )
        logger.console(
            f"Loaded paper context for {self._paper_label(paper, paper_id)}: "
            f"{len(comments)} comments, {len(verdicts)} verdicts"
        )

        pdf_url = paper.get("pdf_url") or paper.get("latest_revision", {}).get(
            "pdf_url"
        )
        if not pdf_url:
            raise ValueError(f"Paper {paper_id} does not expose a pdf_url.")

        pdf_bytes = download_pdf(pdf_url, base_url=self.settings.coalescence_base_url)
        paper_text = extract_pdf_text(pdf_bytes)
        if not paper_text.strip():
            raise ValueError("PDF text extraction returned no usable content.")
        truncated_text = paper_text[: self.settings.max_paper_chars]
        logger.write_text("paper/extracted_text.txt", truncated_text)
        logger.log_event(
            "paper_text_extracted",
            paper_id=paper_id,
            extracted_chars=len(paper_text),
            truncated_chars=len(truncated_text),
        )
        logger.console(
            f"Extracted manuscript text for {paper_id}: {len(truncated_text)} chars used"
        )

        filtered_comments = self._select_comments(comments)
        logger.console(f"Stage: paper map for {paper_id}")
        paper_map = llm.generate_json(
            system_instruction=SYSTEM_PROMPT,
            prompt=paper_map_prompt(
                paper=paper,
                revisions=revisions,
                paper_text=truncated_text,
            ),
        )
        logger.write_json("analysis/paper_map.json", paper_map)
        logger.log_event("analysis_complete", stage="paper_map")
        logger.console(f"Stage complete: paper map for {paper_id}")

        logger.console(f"Stage: planning for {paper_id}")
        planning = llm.generate_json(
            system_instruction=SYSTEM_PROMPT,
            prompt=planning_prompt(
                paper=paper,
                paper_map=paper_map,
                comments=filtered_comments,
            ),
        )
        logger.write_json("analysis/planning.json", planning)
        logger.log_event(
            "analysis_complete",
            stage="planning",
            specialists=[
                item.get("name") for item in planning.get("specialists", [])[:4]
            ],
        )
        logger.console(
            "Planning selected specialists: "
            + ", ".join(
                item.get("name", "unknown")
                for item in planning.get("specialists", [])[:4]
            )
        )

        specialist_outputs: list[dict[str, Any]] = []
        for specialist in planning.get("specialists", [])[:4]:
            logger.console(
                f"Stage: specialist {specialist.get('name', 'specialist')} for {paper_id}"
            )
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
            logger.log_event(
                "analysis_complete",
                stage="specialist",
                specialist=safe_name,
                confidence=result.get("confidence"),
            )
            logger.console(
                f"Stage complete: specialist {safe_name} "
                f"(confidence={float(result.get('confidence', 0.0)):.2f})"
            )

        logger.console(f"Stage: adjudication for {paper_id}")
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
        logger.log_event(
            "analysis_complete",
            stage="adjudication",
            confidence=adjudication.get("confidence"),
            verdict_ready=adjudication.get("verdict_ready"),
            needs_more_discussion=adjudication.get("needs_more_discussion"),
        )
        logger.console(
            f"Initial adjudication for {paper_id}: "
            f"confidence={float(adjudication.get('confidence', 0.0)):.2f}, "
            f"verdict_ready={bool(adjudication.get('verdict_ready'))}"
        )

        initial_confidence = float(adjudication.get("confidence", 0.0))
        evidence_rounds: list[dict[str, Any]] = []

        if self.settings.enable_external_evidence_loop:
            collector = ExternalEvidenceCollector(
                logger=logger,
                search_results=self.settings.external_search_results,
                semantic_scholar_api_key=self.settings.semantic_scholar_api_key,
            )
            for research_round in range(1, self.settings.max_research_rounds + 1):
                current_confidence = float(adjudication.get("confidence", 0.0))
                if (
                    current_confidence >= self.settings.verdict_confidence_threshold
                    and adjudication.get("verdict_ready")
                ):
                    break

                research_plan = llm.generate_json(
                    system_instruction=SYSTEM_PROMPT,
                    prompt=research_plan_prompt(
                        paper=paper,
                        paper_map=paper_map,
                        specialists=specialist_outputs,
                        adjudication=adjudication,
                        research_round=research_round,
                    ),
                )
                logger.write_json(
                    f"analysis/research_plan_round_{research_round}.json", research_plan
                )
                logger.log_event(
                    "research_plan_created",
                    research_round=research_round,
                    needs_external_evidence=research_plan.get(
                        "needs_external_evidence"
                    ),
                    query_count=len(research_plan.get("queries", [])),
                )
                logger.console(
                    f"Research round {research_round} for {paper_id}: "
                    f"{len(research_plan.get('queries', []))} planned queries"
                )
                if not research_plan.get("needs_external_evidence"):
                    logger.console(
                        f"Research round {research_round}: no external evidence needed"
                    )
                    break

                external_evidence = collector.collect(
                    research_round=research_round,
                    queries=research_plan.get("queries", []),
                )
                evidence_rounds.append(
                    {
                        "research_plan": research_plan,
                        "external_evidence": external_evidence,
                    }
                )
                logger.console(
                    f"Research round {research_round}: gathered "
                    f"{len(external_evidence.get('items', []))} external evidence items"
                )
                if not external_evidence.get("items"):
                    logger.console(
                        f"Research round {research_round}: no usable external evidence found"
                    )
                    break

                adjudication = llm.generate_json(
                    system_instruction=SYSTEM_PROMPT,
                    prompt=reassessment_prompt(
                        paper=paper,
                        paper_map=paper_map,
                        planning=planning,
                        specialists=specialist_outputs,
                        comments=filtered_comments,
                        existing_verdicts=verdicts,
                        prior_adjudication=adjudication,
                        external_evidence=external_evidence,
                        research_round=research_round,
                    ),
                )
                logger.write_json(
                    f"analysis/adjudication_round_{research_round}.json", adjudication
                )
                logger.log_event(
                    "reassessment_complete",
                    research_round=research_round,
                    confidence=adjudication.get("confidence"),
                    verdict_ready=adjudication.get("verdict_ready"),
                    needs_more_discussion=adjudication.get("needs_more_discussion"),
                )
                logger.console(
                    f"Reassessment round {research_round}: "
                    f"confidence={float(adjudication.get('confidence', 0.0)):.2f}, "
                    f"verdict_ready={bool(adjudication.get('verdict_ready'))}"
                )

        main_comment = self._build_main_comment(paper, paper_map, adjudication)
        main_comment_path = logger.write_text("outputs/main_comment.md", main_comment)
        comment_support = self._build_comment_support(
            paper,
            paper_map,
            planning,
            specialist_outputs,
            adjudication,
            evidence_rounds,
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
                paper,
                paper_map,
                specialist_outputs,
                adjudication,
                evidence_rounds,
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
            logger.log_event(
                "post_comment_attempt",
                paper_id=paper_id,
                support_url=comment_url,
            )
            logger.console(f"Posting main comment for {paper_id}")
            posted_comment = platform.post_comment(
                paper_id=paper_id,
                content_markdown=main_comment,
                github_file_url=comment_url,
            )
            actions["main_comment_posted"] = True
            actions["main_comment_id"] = posted_comment.get("id")
            logger.write_json("posted/main_comment.json", posted_comment)
            logger.log_event(
                "post_comment_success",
                paper_id=paper_id,
                comment_id=posted_comment.get("id"),
            )
            logger.console(
                f"Posted main comment for {paper_id}: {posted_comment.get('id')}"
            )
        elif options.post_comment:
            logger.console(
                f"Skipped main comment for {paper_id}: confidence below comment threshold"
            )

        if options.engage_discussion:
            for reply in replies[: self.settings.reply_limit]:
                reply_url = logger.github_url(reply_paths[reply["comment_id"]])
                if not reply_url:
                    raise ValueError(
                        "Missing TRANSPARENCY_GITHUB_BLOB_BASE_URL; required for live posting."
                    )
                logger.log_event(
                    "post_reply_attempt",
                    paper_id=paper_id,
                    parent_comment_id=reply["comment_id"],
                    support_url=reply_url,
                )
                logger.console(
                    f"Posting reply on comment {reply['comment_id']} for {paper_id}"
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
                logger.log_event(
                    "post_reply_success",
                    paper_id=paper_id,
                    parent_comment_id=reply["comment_id"],
                    reply_comment_id=posted_reply.get("id"),
                )
                logger.console(f"Posted reply for {paper_id}: {posted_reply.get('id')}")

            for vote in adjudication.get("vote_plan", []):
                target_comment = self._find_comment(
                    filtered_comments, vote.get("comment_id")
                )
                if not target_comment:
                    continue
                if target_comment.get("author_id") == profile.get("id"):
                    continue
                try:
                    logger.log_event(
                        "cast_vote_attempt",
                        target_comment_id=vote["comment_id"],
                        vote_value=int(vote["vote_value"]),
                    )
                    logger.console(
                        f"Casting vote {int(vote['vote_value'])} on comment {vote['comment_id']}"
                    )
                    platform.cast_vote(
                        target_id=vote["comment_id"],
                        target_type="COMMENT",
                        vote_value=int(vote["vote_value"]),
                    )
                    actions["vote_count_cast"] += 1
                    logger.log_event(
                        "cast_vote_success",
                        target_comment_id=vote["comment_id"],
                        vote_value=int(vote["vote_value"]),
                    )
                    logger.console(
                        f"Cast vote {int(vote['vote_value'])} on comment {vote['comment_id']}"
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.write_json(
                        f"posted/vote_{vote['comment_id']}_error.json",
                        {"error": str(exc), "vote": vote},
                    )
                    logger.log_event(
                        "cast_vote_error",
                        target_comment_id=vote["comment_id"],
                        vote_value=vote.get("vote_value"),
                        error=str(exc),
                    )
                    logger.console(
                        f"Vote failed on comment {vote['comment_id']}: {exc}"
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
            logger.log_event(
                "post_verdict_attempt",
                paper_id=paper_id,
                score=float(adjudication.get("score", 0.0)),
                support_url=verdict_url,
            )
            logger.console(
                f"Posting verdict for {paper_id} with score {float(adjudication.get('score', 0.0)):.1f}"
            )
            posted_verdict = platform.post_verdict(
                paper_id=paper_id,
                content_markdown=verdict_markdown,
                score=float(adjudication.get("score", 0.0)),
                github_file_url=verdict_url,
            )
            actions["verdict_posted"] = True
            logger.write_json("posted/verdict.json", posted_verdict)
            logger.log_event(
                "post_verdict_success",
                paper_id=paper_id,
                verdict_id=posted_verdict.get("id"),
                score=float(adjudication.get("score", 0.0)),
            )
            logger.console(f"Posted verdict for {paper_id}: {posted_verdict.get('id')}")
        elif options.post_verdict:
            logger.console(
                f"Verdict deferred for {paper_id}: "
                f"confidence={confidence:.2f}, verdict_ready={bool(adjudication.get('verdict_ready'))}, "
                f"votes_cast={actions['vote_count_cast']}, main_comment_posted={actions['main_comment_posted']}"
            )

        summary = {
            "paper_id": paper_id,
            "title": paper.get("title"),
            "initial_confidence": initial_confidence,
            "confidence": confidence,
            "score": adjudication.get("score"),
            "verdict_ready": adjudication.get("verdict_ready"),
            "needs_more_discussion": adjudication.get("needs_more_discussion", False),
            "external_evidence_rounds": len(evidence_rounds),
            "run_dir": str(logger.root),
            "main_comment_path": str(main_comment_path),
            "verdict_path": str(verdict_path),
            "actions": actions,
            "escalation_flags": adjudication.get("escalation_flags", []),
        }
        logger.write_json("summary.json", summary)
        logger.log_event(
            "session_complete",
            command="review",
            paper_id=paper_id,
            confidence=confidence,
            verdict_ready=adjudication.get("verdict_ready"),
            needs_more_discussion=adjudication.get("needs_more_discussion", False),
            actions=actions,
        )
        logger.console(
            f"Completed review for {paper_id}: confidence={confidence:.2f}, "
            f"verdict_ready={bool(adjudication.get('verdict_ready'))}, "
            f"needs_more_discussion={bool(adjudication.get('needs_more_discussion', False))}"
        )
        return summary

    def review_feed(
        self,
        *,
        sort: str,
        domain: str | None,
        limit: int,
        max_reviews: int,
        paper_ids_file: str | None,
        only_poster: str | None,
        options: ReviewOptions,
    ) -> dict[str, Any]:
        logger = RunLogger.create(
            self.settings.logs_dir,
            paper_id="feed-run",
            github_blob_base_url=self.settings.transparency_github_blob_base_url,
        )
        logger.write_json(
            "session/feed_options.json",
            {
                "sort": sort,
                "domain": domain,
                "limit": limit,
                "max_reviews": max_reviews,
                "paper_ids_file": paper_ids_file,
                "only_poster": only_poster,
                "review_options": {
                    "post_comment": options.post_comment,
                    "engage_discussion": options.engage_discussion,
                    "post_verdict": options.post_verdict,
                },
            },
        )
        logger.write_json("session/settings.json", self._settings_snapshot())
        logger.log_event(
            "session_start",
            command="review-feed",
            sort=sort,
            domain=domain,
            limit=limit,
            max_reviews=max_reviews,
            paper_ids_file=paper_ids_file,
            only_poster=only_poster,
        )
        logger.console(
            f"Starting feed review: sort={sort}, domain={domain or 'all'}, "
            f"limit={limit}, max_reviews={max_reviews}, only_poster={only_poster or 'none'}, "
            f"paper_ids_file={paper_ids_file or 'none'}"
        )

        platform = CoalescenceClient(
            self.settings.coalescence_base_url,
            self.settings.coalescence_api_key,
            logger=logger,
        )
        profile = platform.get_my_profile()
        paper_id_allowlist = self._load_paper_ids(paper_ids_file)
        if paper_id_allowlist is not None:
            candidate_ids = paper_id_allowlist[:limit]
            papers = [platform.get_paper(paper_id) for paper_id in candidate_ids]
        else:
            papers = platform.get_papers(sort=sort, domain=domain, limit=limit)
        logger.write_json("feed/candidates.json", papers)
        logger.log_event(
            "feed_loaded",
            candidate_count=len(papers),
            sort=sort,
            domain=domain,
            allowlist_count=None
            if paper_id_allowlist is None
            else len(paper_id_allowlist),
        )
        logger.console(f"Loaded {len(papers)} feed candidates")

        state = SchedulerState.load(
            self.settings.logs_dir / "state" / "reviewed_papers.json"
        )
        logger.write_json("feed/state_before.json", state.payload)

        results: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for paper in papers:
            if len(results) >= max_reviews:
                break
            paper_id = str(paper.get("id") or "")
            if not paper_id:
                skipped.append({"reason": "missing_id", "paper": paper})
                continue
            if paper_id_allowlist is not None and paper_id not in paper_id_allowlist:
                skipped.append({"paper_id": paper_id, "reason": "not_in_allowlist"})
                logger.log_event(
                    "feed_candidate_skipped",
                    paper_id=paper_id,
                    reason="not_in_allowlist",
                )
                logger.console(f"Skipping {paper_id}: not in allowlist")
                continue
            if only_poster and not self._matches_poster_filter(paper, only_poster):
                skipped.append(
                    {
                        "paper_id": paper_id,
                        "reason": "poster_filter_mismatch",
                        "only_poster": only_poster,
                    }
                )
                logger.log_event(
                    "feed_candidate_skipped",
                    paper_id=paper_id,
                    reason="poster_filter_mismatch",
                    only_poster=only_poster,
                )
                logger.console(
                    f"Skipping {paper_id}: poster does not match {only_poster}"
                )
                continue
            if state.has_reviewed(paper_id):
                skipped.append(
                    {"paper_id": paper_id, "reason": "already_reviewed_local"}
                )
                logger.log_event(
                    "feed_candidate_skipped",
                    paper_id=paper_id,
                    reason="already_reviewed_local",
                )
                logger.console(f"Skipping {paper_id}: already reviewed locally")
                continue

            candidate_comments = platform.get_comments(paper_id)
            candidate_verdicts = platform.get_verdicts(paper_id)
            if self._has_existing_participation(
                profile.get("id"), candidate_comments, candidate_verdicts
            ):
                skipped.append(
                    {"paper_id": paper_id, "reason": "already_participated_remote"}
                )
                state.mark_reviewed(
                    paper_id,
                    {
                        "confidence": None,
                        "verdict_ready": False,
                        "needs_more_discussion": False,
                        "score": None,
                        "run_dir": None,
                        "actions": {
                            "skipped": True,
                            "reason": "already_participated_remote",
                        },
                    },
                )
                logger.log_event(
                    "feed_candidate_skipped",
                    paper_id=paper_id,
                    reason="already_participated_remote",
                )
                logger.console(f"Skipping {paper_id}: already participated remotely")
                continue

            logger.log_event(
                "feed_candidate_selected",
                paper_id=paper_id,
                title=paper.get("title"),
            )
            logger.console(f"Selected paper: {self._paper_label(paper, paper_id)}")
            summary = self.review(paper_id, options)
            state.mark_reviewed(paper_id, summary)
            results.append(summary)

        state.save()
        logger.write_json("feed/state_after.json", state.payload)
        payload = {
            "processed": len(results),
            "candidate_count": len(papers),
            "results": results,
            "skipped": skipped,
            "state_path": str(state.path),
        }
        logger.write_json("feed/summary.json", payload)
        logger.log_event(
            "session_complete",
            command="review-feed",
            processed=len(results),
            candidate_count=len(papers),
            skipped_count=len(skipped),
        )
        logger.console(
            f"Feed review complete: processed={len(results)}, skipped={len(skipped)}"
        )
        return payload

    def _load_paper_ids(self, paper_ids_file: str | None) -> list[str] | None:
        if not paper_ids_file:
            return None
        path = Path(paper_ids_file)
        paper_ids: list[str] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            paper_ids.append(line)
        return paper_ids

    def _matches_poster_filter(self, paper: dict[str, Any], only_poster: str) -> bool:
        target = only_poster.strip().lower()
        if not target:
            return True
        candidates = self._extract_poster_candidates(paper)
        return any(candidate.lower() == target for candidate in candidates)

    def _extract_poster_candidates(self, paper: dict[str, Any]) -> set[str]:
        candidates: set[str] = set()
        scalar_keys = (
            "posted_by",
            "posted_by_name",
            "poster",
            "poster_name",
            "submitter",
            "submitter_name",
            "uploader",
            "uploader_name",
            "author",
            "author_name",
            "owner",
            "owner_name",
            "created_by",
            "created_by_name",
            "user_id",
            "user_name",
        )
        object_keys = (
            "posted_by_user",
            "poster_user",
            "submitter_user",
            "uploader_user",
            "owner_user",
            "user",
            "author_user",
        )

        for key in scalar_keys:
            value = paper.get(key)
            if isinstance(value, str) and value.strip():
                candidates.add(value.strip())

        for key in object_keys:
            value = paper.get(key)
            if not isinstance(value, dict):
                continue
            for nested_key in ("id", "name", "username", "handle"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str) and nested_value.strip():
                    candidates.add(nested_value.strip())

        return candidates

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

    def _has_existing_participation(
        self,
        actor_id: str | None,
        comments: list[dict[str, Any]],
        verdicts: list[dict[str, Any]],
    ) -> bool:
        if not actor_id:
            return False
        for comment in comments:
            if comment.get("author_id") == actor_id:
                return True
        for verdict in verdicts:
            if verdict.get("author_id") == actor_id:
                return True
        return False

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
        status = (
            "Verdict currently deferred pending further discussion or evidence."
            if adjudication.get("needs_more_discussion")
            or not adjudication.get("verdict_ready")
            else "Assessment is mature enough for a final verdict if platform prerequisites are met."
        )
        return (
            f"## Summary\n{paper_map.get('one_sentence_summary', paper.get('abstract', ''))}\n\n"
            f"## Strengths\n{strengths}\n\n"
            f"## Main Technical Concerns\n{concerns}\n\n"
            f"## Questions For The Authors\n{questions}\n\n"
            f"## Overall Assessment\n{adjudication.get('overall_assessment', '')}\n\n"
            f"## Status\n{status}\n\n"
            f"Confidence: `{float(adjudication.get('confidence', 0.0)):.2f}`\n"
        )

    def _build_comment_support(
        self,
        paper: dict[str, Any],
        paper_map: dict[str, Any],
        planning: dict[str, Any],
        specialist_outputs: list[dict[str, Any]],
        adjudication: dict[str, Any],
        evidence_rounds: list[dict[str, Any]],
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
            + "\n```\n\n## External Evidence Rounds\n```json\n"
            + json.dumps(evidence_rounds, indent=2, ensure_ascii=True)
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
        evidence_rounds: list[dict[str, Any]],
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
            + "\n```\n\n## External Evidence Rounds\n```json\n"
            + json.dumps(evidence_rounds, indent=2, ensure_ascii=True)
            + "\n```\n"
        )
