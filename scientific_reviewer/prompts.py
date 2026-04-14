from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """You are a scientific paper review agent operating on Coalescence.

Core policy:
- Review for scientific validity, technical quality, novelty, reproducibility, clarity, and limitations.
- Be evidence-grounded. Every important conclusion must point back to manuscript evidence or clearly marked uncertainty.
- Use AI as an assistive reviewer, not as a reckless final arbiter.
- Follow a hierarchical process: manuscript grounding, specialist analysis, cross-examination, and meta-synthesis.
- Treat discussion and rebuttal content cautiously; do not become overly deferential because another actor sounds confident.
- Prefer specific, actionable criticism over generic review language.
- Flag when methodological novelty or theoretical validity cannot be assessed confidently from the available evidence.
- Do not use external exact-paper lookups for the reviewed paper. Work from the manuscript, the Coalescence thread, and the platform metadata.
- If confidence is low, recommend more discussion instead of forcing a verdict.
- Voting is part of scientific discussion hygiene, not a popularity action.
- Upvotes are appropriate for comments that are materially correct, evidence-grounded, technically helpful, or that surface an important concern clearly.
- Downvotes are appropriate for comments that are materially misleading, unsupported by the manuscript, overconfident without evidence, or that distort the technical record.
- It is acceptable to abstain from voting. Do not force a vote when the rationale is weak or mixed.
- Replies and votes should strengthen the paper discussion, not create noise.
"""


def paper_map_prompt(
    *,
    paper: dict[str, Any],
    revisions: list[dict[str, Any]],
    paper_text: str,
) -> str:
    return f"""
Build a structured paper map for this manuscript.

Return JSON with exactly these keys:
- paper_type: string
- one_sentence_summary: string
- contributions: list[string]
- core_claims: list[object with keys claim, evidence, location_hint]
- methods: list[object with keys method, evidence, location_hint]
- experiments: list[object with keys experiment, evidence, location_hint]
- reproducibility: list[string]
- limitations: list[object with keys limitation, evidence, location_hint]
- validity_risks: list[object with keys risk, severity, evidence, location_hint]
- unresolved_questions: list[string]

Paper metadata:
{json.dumps(paper, indent=2, ensure_ascii=True)}

Revision metadata:
{json.dumps(revisions[:5], indent=2, ensure_ascii=True)}

Paper text:
{paper_text}
""".strip()


def planning_prompt(
    *,
    paper: dict[str, Any],
    paper_map: dict[str, Any],
    comments: list[dict[str, Any]],
) -> str:
    return f"""
Plan a hierarchical review strategy for this paper.

Return JSON with exactly these keys:
- review_focus: string
- reasons: list[string]
- specialists: list[object with keys name, remit]
- comment_themes_to_check: list[string]
- caution_flags: list[string]

Choose 4 specialists from this set:
- methodology_validity
- experimental_rigor
- novelty_and_positioning
- theory_and_formalism
- reproducibility_and_reporting
- ethics_and_scope

Paper metadata:
{json.dumps(paper, indent=2, ensure_ascii=True)}

Paper map:
{json.dumps(paper_map, indent=2, ensure_ascii=True)}

Existing discussion summary:
{json.dumps(_compact_comments(comments), indent=2, ensure_ascii=True)}
""".strip()


def specialist_prompt(
    *,
    paper: dict[str, Any],
    paper_map: dict[str, Any],
    specialist: dict[str, Any],
) -> str:
    return f"""
You are the specialist reviewer `{specialist["name"]}`.
Remit: {specialist["remit"]}

Return JSON with exactly these keys:
- specialist: string
- stance: string
- confidence: number
- strengths: list[object with keys point, evidence, location_hint]
- concerns: list[object with keys point, severity, evidence, location_hint, suggested_action]
- questions: list[string]
- score_signal: object with keys direction, magnitude, rationale

Focus on scientific validity and avoid generic praise.

Paper metadata:
{json.dumps(paper, indent=2, ensure_ascii=True)}

Paper map:
{json.dumps(paper_map, indent=2, ensure_ascii=True)}
""".strip()


def adjudication_prompt(
    *,
    paper: dict[str, Any],
    paper_map: dict[str, Any],
    planning: dict[str, Any],
    specialists: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    existing_verdicts: list[dict[str, Any]],
) -> str:
    return f"""
Synthesize the specialist outputs into a final meta-review plan.

Return JSON with exactly these keys:
- overall_assessment: string
- confidence: number
- consensus_strengths: list[string]
- consensus_concerns: list[object with keys point, severity, rationale]
- disagreement_points: list[string]
- questions_for_authors: list[string]
- main_comment_should_post: boolean
- score: number
- verdict_ready: boolean
- verdict_rationale: string
- reply_plan: list[object with keys comment_id, stance, rationale, evidence]
- vote_plan: list[object with keys comment_id, vote_value, rationale]
- escalation_flags: list[string]

Rules:
- Do not recommend a verdict unless the paper has been assessed from all major technical angles.
- Prefer replying only when another comment is materially correct and worth reinforcing, or materially wrong and worth correcting.
- Recommend votes only for comments from other actors and only when the rationale is strong.
- Upvote when a comment is technically sound, evidence-grounded, and helpful to the discussion.
- Downvote when a comment is technically unsound, materially misleading, or unsupported by the manuscript evidence.
- Abstain when a comment is mixed, underspecified, or not important enough to justify a vote.
- Do not propose votes just to satisfy platform prerequisites; only propose them when the scientific-discussion rationale is real.

Paper metadata:
{json.dumps(paper, indent=2, ensure_ascii=True)}

Paper map:
{json.dumps(paper_map, indent=2, ensure_ascii=True)}

Planning output:
{json.dumps(planning, indent=2, ensure_ascii=True)}

Specialist outputs:
{json.dumps(specialists, indent=2, ensure_ascii=True)}

Existing comments:
{json.dumps(_compact_comments(comments), indent=2, ensure_ascii=True)}

Existing verdicts:
{json.dumps(existing_verdicts, indent=2, ensure_ascii=True)}
""".strip()


def _compact_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for comment in comments:
        compact.append(
            {
                "id": comment.get("id"),
                "parent_id": comment.get("parent_id"),
                "author_id": comment.get("author_id"),
                "author_type": comment.get("author_type"),
                "net_score": comment.get("net_score"),
                "created_at": comment.get("created_at"),
                "content_markdown": (comment.get("content_markdown") or "")[:1800],
            }
        )
    return compact
