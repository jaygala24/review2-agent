#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if [[ ! -f ".env" ]]; then
  echo "Missing .env in ${REPO_ROOT}" >&2
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv/bin/python in ${REPO_ROOT}" >&2
  exit 1
fi

INTERVAL_SECONDS="${INTERVAL_SECONDS:-1200}"
REVIEW_SORT="${REVIEW_SORT:-new}"
REVIEW_LIMIT="${REVIEW_LIMIT:-10}"
MAX_REVIEWS="${MAX_REVIEWS:-1}"
POST_COMMENT="${POST_COMMENT:-true}"
ENGAGE_DISCUSSION="${ENGAGE_DISCUSSION:-true}"
POST_VERDICT="${POST_VERDICT:-false}"
DOMAIN="${DOMAIN:-}"
LOG_FILE="${LOG_FILE:-logs/tmux-feed.log}"

mkdir -p "$(dirname "${LOG_FILE}")"

build_args() {
  local args=(
    -m scientific_reviewer review-feed
    --sort "${REVIEW_SORT}"
    --limit "${REVIEW_LIMIT}"
    --max-reviews "${MAX_REVIEWS}"
  )

  if [[ -n "${DOMAIN}" ]]; then
    args+=(--domain "${DOMAIN}")
  fi
  if [[ "${POST_COMMENT}" == "true" ]]; then
    args+=(--post-comment)
  fi
  if [[ "${ENGAGE_DISCUSSION}" == "true" ]]; then
    args+=(--engage-discussion)
  fi
  if [[ "${POST_VERDICT}" == "true" ]]; then
    args+=(--post-verdict)
  fi

  args+=("$@")
  printf '%s\n' "${args[@]}"
}

mapfile -t BASE_ARGS < <(build_args "$@")

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] starting feed loop" | tee -a "${LOG_FILE}"
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] interval=${INTERVAL_SECONDS}s sort=${REVIEW_SORT} limit=${REVIEW_LIMIT} max_reviews=${MAX_REVIEWS}" | tee -a "${LOG_FILE}"

while true; do
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] running review-feed" | tee -a "${LOG_FILE}"
  if ".venv/bin/python" "${BASE_ARGS[@]}" 2>&1 | tee -a "${LOG_FILE}"; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] run complete" | tee -a "${LOG_FILE}"
  else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] run failed" | tee -a "${LOG_FILE}"
  fi
  sleep "${INTERVAL_SECONDS}"
done
