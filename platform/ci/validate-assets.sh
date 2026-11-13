#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW_FILE="$ROOT_DIR/.gitea/workflows/pipeline.yml"

bash -n \
  "$ROOT_DIR/ci/run-pipeline.sh" \
  "$ROOT_DIR/ci/notify-workflow04.sh" \
  "$ROOT_DIR/ci/validate-assets.sh"

jq -e '
  .schema_version == "2.0" and
  .implementation_profile == "python-fastapi-3.12" and
  .fuzzing.enabled == false and
  (.artifacts_upload.package_name | type == "string") and
  (.artifacts_upload.package_name | length > 0)
' "$ROOT_DIR/ci/policy.json" >/dev/null

grep -Fq 'types: [opened, reopened]' "$WORKFLOW_FILE"
if grep -Fq 'synchronized' "$WORKFLOW_FILE"; then
  echo "pipeline.yml must not subscribe to pull_request synchronized" >&2
  exit 1
fi

for input_name in pr_number context_version repair_attempt run_id; do
  grep -Eq "^[[:space:]]{6}${input_name}:" "$WORKFLOW_FILE"
done

grep -Fq 'run-name: FastAPI CI' "$WORKFLOW_FILE"
grep -Fq 'AI repair context: input=' "$WORKFLOW_FILE"

grep -Fq 'CI_ARTIFACT_OWNER: ${{ vars.AI_ARTIFACT_OWNER }}' "$WORKFLOW_FILE"
if grep -Eq 'vars\.CI_' "$WORKFLOW_FILE"; then
  echo "Gitea user-defined Variables cannot start with CI" >&2
  exit 1
fi
grep -Fq 'CI_GITEA_TOKEN: ${{ secrets.AI_GITEA_TOKEN }}' "$WORKFLOW_FILE"
grep -Fq -- "--header 'X-Execution-Mode: async'" "$ROOT_DIR/ci/notify-workflow04.sh"
grep -Fq 'Quality gate passed; Workflow 04 callback is not required.' "$ROOT_DIR/ci/notify-workflow04.sh"
grep -Fq 'AI_PR_NUMBER' "$ROOT_DIR/ci/run-pipeline.sh"
grep -Fq 'workflow_context' "$ROOT_DIR/ci/run-pipeline.sh"

if command -v ruby >/dev/null 2>&1; then
  ruby -e 'require "yaml"; YAML.safe_load(File.read(ARGV.fetch(0)), aliases: true)' "$WORKFLOW_FILE"
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import yaml' >/dev/null 2>&1; then
  python3 -c 'import pathlib, sys, yaml; yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))' "$WORKFLOW_FILE"
else
  echo "WARN: YAML parser is unavailable; structural grep checks were used" >&2
fi

echo "FastAPI platform assets: static validation passed"
