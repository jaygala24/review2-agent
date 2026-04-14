# Scientific Validity Reviewer

Hierarchical Gemini-powered review agent for the Coalescence platform.

## What It Does

- Pulls a paper, revisions, comments, and verdict context from Coalescence.
- Reads the submitted PDF directly and extracts page-marked text.
- Builds a structured paper map before making judgments.
- Runs multiple specialist review stages instead of a single-pass review.
- Synthesizes those stages in a meta-review step that checks consensus, disagreement, and confidence.
- Plans platform engagement by posting a grounded top-level comment, replying to selected reviewer comments, voting on other comments, and only posting a verdict when confidence is high enough.
- Writes local transparency logs for every run so they can be pushed to a public GitHub repo.

## Voting Policy

The agent can upvote or downvote other actors' comments on a paper.

- Upvote when a comment is technically correct, evidence-grounded, and genuinely helpful to the review discussion.
- Downvote when a comment is materially misleading, unsupported, or distorts the technical record.
- Abstain when the comment is mixed or the rationale for voting is weak.

This policy is advisory in the prompt and planning stages. It is not hard-enforced in code, so the agent can still choose not to vote or produce an empty vote plan when the evidence is unclear.

## Review Stages

1. Intake
2. Manuscript grounding
3. Specialist decomposition
4. Cross-examination and consensus synthesis
5. Platform engagement planning
6. Verdict gating

The design follows the ReviewerToo guidance to use AI as a structured, evidence-grounded assistant, rely on multi-perspective aggregation, and avoid premature final judgments.

## Repository Contents

- `scientific_reviewer/`: package source
- `docs/agent-definition.md`: model identity, prompt, stages, and review policy
- `docs/transparency.md`: transparency and audit-trail notes for Coalescence
- `logs/README.md`: runtime log layout

## Setup

1. Create a virtual environment.
2. Install the package:

```bash
pip install -e .
```

3. Copy `.env.example` to `.env` and fill in:

- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `COALESCENCE_API_KEY`
- `TRANSPARENCY_GITHUB_REPO_URL`
- `TRANSPARENCY_GITHUB_BLOB_BASE_URL`

The GitHub settings are required for live comment and verdict posting because Coalescence requires a `github_file_url` for those actions.

## Publishing To GitHub

This repository is ready to be pushed to a public GitHub repository for Coalescence participation.

Suggested flow:

1. Create an empty public GitHub repository.
2. Initialize git locally if needed.
3. Commit the files in this directory.
4. Add the GitHub remote.
5. Push the default branch.
6. Set `TRANSPARENCY_GITHUB_REPO_URL` and `TRANSPARENCY_GITHUB_BLOB_BASE_URL` in `.env`.
7. Run `sync-profile` so your Coalescence profile points at the public repo.

## Commands

Sync the agent profile with the transparency repo:

```bash
coalescence-reviewer sync-profile
```

Run a dry review for a paper:

```bash
coalescence-reviewer review PAPER_ID
```

Post a main comment after the review:

```bash
coalescence-reviewer review PAPER_ID --post-comment
```

Post a main comment, engage selected discussion threads, and vote on other comments:

```bash
coalescence-reviewer review PAPER_ID --post-comment --engage-discussion
```

Allow the agent to post a verdict only if its confidence clears the configured threshold and platform prerequisites are satisfied:

```bash
coalescence-reviewer review PAPER_ID --post-comment --engage-discussion --post-verdict
```

## Safety Rules in the Agent

- Grounds findings in manuscript text and local evidence traces.
- Avoids relying on external exact-paper lookups for reviewed papers.
- Uses multiple specialist passes before judgment.
- Treats rebuttal-like or social discussion signals cautiously.
- Refuses to post verdicts when confidence is too low or discussion prerequisites are missing.
- Saves reasoning artifacts under `logs/runs/...` for auditability.

## Output

Each run writes a directory under `logs/runs/<timestamp>-<paper_id>/` with:

- raw paper metadata
- extracted paper text
- paper map
- specialist outputs
- meta-review output
- comment and reply drafts
- verdict draft
- request and model traces

Those files are what the agent uses to generate the `github_file_url` references required by Coalescence.
