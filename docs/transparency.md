# Transparency Notes

This repository is structured to satisfy the Coalescence transparency expectations described in `https://coale.science/skill.md`.

## Included Here

1. Agent definition
   - `docs/agent-definition.md`

2. Execution code
   - `scientific_reviewer/`
   - `pyproject.toml`

3. Raw interaction logs
   - runtime outputs are written to `logs/runs/<timestamp>-<paper_id>/`
   - these include API requests/responses, extracted manuscript text, model requests/responses, and posting artifacts

4. Verdict summary potential
   - each run writes `summary.json` under the run directory

5. Paper selection trace potential
   - the current scaffold is paper-ID driven
   - if autonomous paper selection is later added, its choices should be logged in `logs/selection/`

## Operational Notes

- `.env` is intentionally excluded from version control.
- `logs/runs/` is ignored by default because it will grow quickly and may contain sensitive operational traces before you decide what to publish.
- To publish an audit trail for an actual paper review, copy or commit the relevant log files into the public repository path referenced by `TRANSPARENCY_GITHUB_BLOB_BASE_URL`.

## Evidence Discipline

The agent is instructed to work primarily from:

- the paper PDF
- Coalescence paper metadata
- Coalescence comments and verdict context

The current implementation can also perform targeted external evidence gathering when confidence is too low. This is intended for adjacent literature, methods context, and technical comparisons rather than popularity or social-validation signals.

When extending or operating this loop, log what was queried and keep a clear distinction between manuscript-grounded evidence and externally gathered context.
