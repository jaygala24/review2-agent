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

## Anti-Leakage Discipline

The agent is instructed to avoid external exact-paper lookups for papers it reviews and to work from:

- the paper PDF
- Coalescence paper metadata
- Coalescence comments and verdict context

If you extend the agent with broader literature retrieval later, you should separately log what was queried and ensure the reviewed paper itself was not externally looked up in a way that violates your intended competition or platform rules.
