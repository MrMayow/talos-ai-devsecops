#!/usr/bin/env bash
set -Eeuo pipefail

# Calls Workflow 04 only after CI evidence has been published. Secrets are
# supplied by Gitea Actions and are never stored in this repository.

if [ "${AI_REVISE_ENABLED:-false}" != "true" ]; then
  echo "Workflow 04 callback is disabled: AI_REVISE_ENABLED != true"
  exit 0
fi

: "${SIM_INTERNAL_URL:?Set repository variable SIM_INTERNAL_URL}"
: "${SIM_WORKFLOW04_ID:?Set repository variable SIM_WORKFLOW04_ID}"
: "${SIM_WORKFLOW_API_KEY:?Set repository secret SIM_WORKFLOW_API_KEY}"
: "${CI_GITEA_URL:?pipeline must map repository variable AI_GITEA_URL}"
: "${CI_GITEA_USER:?pipeline must map repository variable AI_GITEA_USER}"
: "${CI_GITEA_TOKEN:?pipeline must map repository secret AI_GITEA_TOKEN}"
: "${CI_ARTIFACT_OWNER:?pipeline must map repository variable AI_ARTIFACT_OWNER}"
: "${AI_COMMIT_SHA:?AI_COMMIT_SHA is required}"
: "${AI_BRANCH:?AI_BRANCH is required}"
: "${AI_PR_NUMBER:?AI_PR_NUMBER is required}"
: "${AI_CONTEXT_VERSION:?AI_CONTEXT_VERSION is required}"
: "${AI_RUN_ID:?AI_RUN_ID is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_RUN_NUMBER:?GITHUB_RUN_NUMBER is required}"

OWNER="${GITHUB_REPOSITORY%%/*}"
REPO="${GITHUB_REPOSITORY#*/}"
PR_NUMBER="$AI_PR_NUMBER"
CONTEXT_VERSION="$AI_CONTEXT_VERSION"
RUN_ID="$AI_RUN_ID"

if ! printf '%s' "$PR_NUMBER" | grep -Eq '^[1-9][0-9]*$'; then
  echo "AI_PR_NUMBER must be a positive integer" >&2
  exit 2
fi
if ! printf '%s' "$CONTEXT_VERSION" | grep -Eq '^[A-Za-z0-9_.-]{1,100}$'; then
  echo "AI_CONTEXT_VERSION has an invalid format" >&2
  exit 2
fi
if ! printf '%s' "$RUN_ID" | grep -Eq '^run-[0-9]{8}-[0-9]{6}-[a-z0-9]{6}$'; then
  echo "AI_RUN_ID has an invalid format" >&2
  exit 2
fi

ARTIFACT_OWNER="$CI_ARTIFACT_OWNER"
ARTIFACT_PACKAGE="${CI_ARTIFACT_PACKAGE:-ci-artifacts}"
ARTIFACT_VERSION="${GITHUB_RUN_NUMBER}-$(printf '%s' "$AI_COMMIT_SHA" | cut -c1-12)"
ARTIFACT_BASE="${CI_GITEA_URL%/}/api/packages/${ARTIFACT_OWNER}/generic/${ARTIFACT_PACKAGE}/${ARTIFACT_VERSION}"
CONTEXT_OWNER="${CI_CONTEXT_OWNER:-$ARTIFACT_OWNER}"
CONTEXT_PACKAGE="${CI_CONTEXT_PACKAGE:-development-contracts}"

for SAFE_VALUE in "$ARTIFACT_OWNER" "$ARTIFACT_PACKAGE" "$ARTIFACT_VERSION" "$CONTEXT_OWNER" "$CONTEXT_PACKAGE"; do
  if ! printf '%s' "$SAFE_VALUE" | grep -Eq '^[A-Za-z0-9_.-]{1,100}$'; then
    echo "Artifact or context coordinate has an invalid format: ${SAFE_VALUE}" >&2
    exit 2
  fi
done

DRY_RUN="${AI_REVISE_DRY_RUN:-true}"
case "$DRY_RUN" in
  true|false) ;;
  *) echo "AI_REVISE_DRY_RUN must be true or false" >&2; exit 2 ;;
esac

# Workflow 04 must never receive a pointer to an incomplete or stale evidence
# package. A failed quality gate is valid input; a missing package is not.
for REQUIRED_ARTIFACT in findings.json ci-summary.json test-report.md artifact-manifest.json; do
  if ! curl --fail-with-body --silent --show-error \
    --user "${CI_GITEA_USER}:${CI_GITEA_TOKEN}" \
    --output /dev/null \
    "${ARTIFACT_BASE}/${REQUIRED_ARTIFACT}"
  then
    echo "Workflow 04 was not called: missing published artifact ${REQUIRED_ARTIFACT}" >&2
    exit 3
  fi
done

LOCAL_MANIFEST="artifacts/artifact-manifest.json"
if ! jq -e \
  --arg commit_sha "$AI_COMMIT_SHA" \
  --arg artifact_version "$ARTIFACT_VERSION" \
  '.commit_sha == $commit_sha and .artifact_version == $artifact_version' \
  "$LOCAL_MANIFEST" >/dev/null
then
  echo "Local artifact manifest does not match the current commit and package version" >&2
  exit 3
fi

REMOTE_MANIFEST="${TMPDIR:-/tmp}/artifact-manifest-${GITHUB_RUN_NUMBER}.json"
curl --fail-with-body --silent --show-error \
  --user "${CI_GITEA_USER}:${CI_GITEA_TOKEN}" \
  --output "$REMOTE_MANIFEST" \
  "${ARTIFACT_BASE}/artifact-manifest.json"

if ! jq -e \
  --arg commit_sha "$AI_COMMIT_SHA" \
  --arg artifact_version "$ARTIFACT_VERSION" \
  '.commit_sha == $commit_sha and .artifact_version == $artifact_version' \
  "$REMOTE_MANIFEST" >/dev/null
then
  echo "Published artifact manifest belongs to another run" >&2
  exit 3
fi

LOCAL_SUMMARY="artifacts/ci-summary.json"
if ! jq -e \
  --arg commit_sha "$AI_COMMIT_SHA" \
  --arg artifact_version "$ARTIFACT_VERSION" \
  '.commit_sha == $commit_sha and .artifact.version == $artifact_version and (.quality_gate.passed | type == "boolean")' \
  "$LOCAL_SUMMARY" >/dev/null
then
  echo "Local CI summary does not match the current commit and package version" >&2
  exit 3
fi
if jq -e '.quality_gate.passed == true' "$LOCAL_SUMMARY" >/dev/null; then
  echo "Quality gate passed; Workflow 04 callback is not required."
  exit 0
fi

CURRENT_ATTEMPT="${AI_REPAIR_ATTEMPT:-0}"
if ! printf '%s' "$CURRENT_ATTEMPT" | grep -Eq '^(0|[1-5])$'; then
  echo "AI_REPAIR_ATTEMPT must be an integer from 0 to 5" >&2
  exit 2
fi

# A repair can create several commits. Use the greatest explicit attempt marker
# and the dispatch input, then request exactly the next attempt.
LAST_COMMIT_ATTEMPT="$({
  git log --format=%s "$AI_COMMIT_SHA" 2>/dev/null || true
} | sed -n 's/.*\[attempt \([0-9][0-9]*\)\].*/\1/p' | sort -n | tail -n 1)"

if [ -n "$LAST_COMMIT_ATTEMPT" ] && [ "$LAST_COMMIT_ATTEMPT" -gt "$CURRENT_ATTEMPT" ]; then
  CURRENT_ATTEMPT="$LAST_COMMIT_ATTEMPT"
fi
ATTEMPT=$((CURRENT_ATTEMPT + 1))
MAX_REPAIR_ATTEMPTS="${AI_MAX_REPAIR_ATTEMPTS:-5}"
if ! printf '%s' "$MAX_REPAIR_ATTEMPTS" | grep -Eq '^[1-5]$'; then
  echo "AI_MAX_REPAIR_ATTEMPTS must be an integer from 1 to 5" >&2
  exit 2
fi
if [ "$ATTEMPT" -gt "$MAX_REPAIR_ATTEMPTS" ]; then
  echo "Automatic repair limit (${MAX_REPAIR_ATTEMPTS}) reached; human intervention is required."
  exit 0
fi

PAYLOAD="$(jq -n \
  --arg run_id "$RUN_ID" \
  --arg owner "$OWNER" \
  --arg repo "$REPO" \
  --arg branch "$AI_BRANCH" \
  --arg commit_sha "$AI_COMMIT_SHA" \
  --argjson pr_number "$PR_NUMBER" \
  --arg artifact_owner "$ARTIFACT_OWNER" \
  --arg artifact_package "$ARTIFACT_PACKAGE" \
  --arg artifact_version "$ARTIFACT_VERSION" \
  --arg context_owner "$CONTEXT_OWNER" \
  --arg context_package "$CONTEXT_PACKAGE" \
  --arg context_version "$CONTEXT_VERSION" \
  --argjson attempt "$ATTEMPT" \
  --argjson dry_run "$DRY_RUN" \
  '{
    input: {
      run_id: $run_id,
      owner: $owner,
      repo: $repo,
      branch: $branch,
      commit_sha: $commit_sha,
      pr_number: $pr_number,
      artifact_owner: $artifact_owner,
      artifact_package: $artifact_package,
      artifact_version: $artifact_version,
      context_owner: $context_owner,
      context_package: $context_package,
      context_version: $context_version,
      attempt: $attempt,
      dry_run: $dry_run
    }
  }')"

CALLBACK_URL="${SIM_INTERNAL_URL%/}/api/workflows/${SIM_WORKFLOW04_ID}/execute"
RESPONSE_FILE="${TMPDIR:-/tmp}/workflow04-callback-${GITHUB_RUN_NUMBER}.json"

HTTP_CODE="$(curl --silent --show-error \
  --output "$RESPONSE_FILE" \
  --write-out '%{http_code}' \
  --request POST "$CALLBACK_URL" \
  --header 'Content-Type: application/json' \
  --header "x-api-key: ${SIM_WORKFLOW_API_KEY}" \
  --header 'X-Execution-Mode: async' \
  --data "$PAYLOAD")"

case "$HTTP_CODE" in
  200|202)
    echo "Workflow 04 queued asynchronously: HTTP ${HTTP_CODE}; attempt=${ATTEMPT}; PR=${PR_NUMBER}"
    jq '{success, async, jobId, executionId, message, statusUrl}' "$RESPONSE_FILE" 2>/dev/null || true
    ;;
  *)
    echo "SIM rejected Workflow 04 callback: HTTP ${HTTP_CODE}" >&2
    sed -n '1,80p' "$RESPONSE_FILE" >&2 || true
    exit 1
    ;;
esac
