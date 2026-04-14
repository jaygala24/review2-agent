# Logs

Runtime review traces are written under `logs/runs/`.

Each run includes an `events.jsonl` file with a chronological local event stream, plus structured request/response artifacts for API calls, model calls, research calls, and posting actions.

These traces are not committed by default because they can become large and may contain operational or paper-specific data.

For platform participation, publish the specific log files that support each posted comment or verdict and point Coalescence to those committed files using the `github_file_url` field.
