#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
ARTIFACTS_DIR="$ROOT_DIR/artifacts"
POLICY_FILE="$ROOT_DIR/ci/policy.json"
PROFILE_DOCKERFILE="$ROOT_DIR/ci/profiles/python-fastapi-3.12.Dockerfile"

PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-python:3.12-slim}"
SEMGREP_IMAGE="${SEMGREP_IMAGE:-semgrep/semgrep:latest}"
ZAP_IMAGE="${ZAP_IMAGE:-ghcr.io/zaproxy/zaproxy:stable}"
CURL_IMAGE="${CURL_IMAGE:-curlimages/curl:latest}"

SHORT_SHA=""
ARTIFACT_VERSION=""
PACKAGE_NAME="ci-artifacts"
ARTIFACT_OWNER=""
ARTIFACT_BASE=""

TEST_IMAGE=""
RUNTIME_IMAGE=""
NETWORK_NAME=""
APP_CONTAINER=""

UNIT_EXIT=125
UNIT_STATUS="not_run"

SEMGREP_EXIT=125
SEMGREP_STATUS="not_run"
SEMGREP_FINDINGS=0

RUNTIME_EXIT=125
RUNTIME_STATUS="not_run"

ZAP_EXIT=125
ZAP_STATUS="not_run"
ZAP_ALERTS=0

UPLOAD_EXIT=1
UPLOAD_STATUS="not_run"

QUALITY_PASSED=false
BLOCKING_COUNT=0

say() {
  printf '\n============================================================\n'
  printf '%s\n' "$1"
  printf '============================================================\n'
}

require_env() {
  local name="$1"

  if [ -z "${!name:-}" ]; then
    echo "Не задана обязательная переменная: $name" >&2
    exit 2
  fi
}

classify_exit() {
  local exit_code="$1"

  case "$exit_code" in
    0) echo "passed" ;;
    125|126|127) echo "infra_error" ;;
    *) echo "failed" ;;
  esac
}

looks_like_network_failure() {
  local log_file="$1"

  [ -f "$log_file" ] && grep -Eqi \
    'temporary failure in name resolution|no address associated with hostname|could not resolve host|name or service not known|network is unreachable|i/o timeout|tls handshake timeout|connection timed out' \
    "$log_file"
}

cleanup() {
  set +e

  if docker inspect "$APP_CONTAINER" >/dev/null 2>&1; then
    docker logs "$APP_CONTAINER" > "$ARTIFACTS_DIR/runtime.log" 2>&1 || true
    docker rm -f "$APP_CONTAINER" >/dev/null 2>&1 || true
  fi

  docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
}

trap cleanup EXIT

prepare_workspace() {
  test -n "$ROOT_DIR"
  test "$ROOT_DIR" != "/"
  test "$ARTIFACTS_DIR" = "$ROOT_DIR/artifacts"
  rm -rf -- "$ARTIFACTS_DIR"
  mkdir -p "$ARTIFACTS_DIR"
  chmod 0777 "$ARTIFACTS_DIR"
}

validate_inputs() {
  require_env CI_GITEA_USER
  require_env CI_GITEA_TOKEN
  require_env CI_GITEA_URL
  require_env CI_ARTIFACT_OWNER
  require_env GITHUB_REPOSITORY
  require_env GITHUB_RUN_NUMBER
  require_env AI_COMMIT_SHA
  require_env AI_BRANCH
  require_env AI_PR_NUMBER
  require_env AI_CONTEXT_VERSION
  require_env AI_REPAIR_ATTEMPT
  require_env AI_RUN_ID

  if [ ! -s "$POLICY_FILE" ]; then
    echo "Отсутствует обязательный policy: ci/policy.json" >&2
    exit 2
  fi

  if [ ! -s "$PROFILE_DOCKERFILE" ]; then
    echo "Отсутствует platform build template: $PROFILE_DOCKERFILE" >&2
    exit 2
  fi

  jq -e '
    .schema_version == "2.0" and
    .implementation_profile == "python-fastapi-3.12" and
    (.unit_tests.required | type == "boolean") and
    (.static_analysis.semgrep.required | type == "boolean") and
    (.static_analysis.semgrep.block_on_any_finding | type == "boolean") and
    (.runtime_smoke.required | type == "boolean") and
    (.runtime_smoke.health_path | type == "string") and
    (.dynamic_analysis.zap_baseline.required | type == "boolean") and
    (.dynamic_analysis.zap_baseline.warnings_block | type == "boolean") and
    (.dynamic_analysis.zap_baseline.warning_exit_codes | type == "array") and
    (.dynamic_analysis.zap_baseline.blocking_exit_codes | type == "array") and
    .fuzzing.enabled == false and
    (.artifacts_upload.required | type == "boolean") and
    (.artifacts_upload.package_name | type == "string")
  ' "$POLICY_FILE" >/dev/null

  if [ "$GITHUB_REPOSITORY" != "labadmin/demo-fastapi" ]; then
    echo "Repository вне CI allowlist: $GITHUB_REPOSITORY" >&2
    exit 2
  fi

  if ! printf '%s' "$AI_COMMIT_SHA" | grep -Eq '^[0-9a-fA-F]{40,64}$'; then
    echo "AI_COMMIT_SHA имеет неверный формат" >&2
    exit 2
  fi

  if ! printf '%s' "$AI_PR_NUMBER" | grep -Eq '^[1-9][0-9]*$'; then
    echo "AI_PR_NUMBER должен быть положительным целым числом" >&2
    exit 2
  fi

  if ! printf '%s' "$AI_CONTEXT_VERSION" | grep -Eq '^[A-Za-z0-9_.-]{1,100}$'; then
    echo "AI_CONTEXT_VERSION имеет неверный формат" >&2
    exit 2
  fi

  if ! printf '%s' "$AI_REPAIR_ATTEMPT" | grep -Eq '^(0|[1-9][0-9]*)$' || [ "$AI_REPAIR_ATTEMPT" -gt 100 ]; then
    echo "AI_REPAIR_ATTEMPT должен быть целым числом от 0 до 100" >&2
    exit 2
  fi

  if ! printf '%s' "$AI_RUN_ID" | grep -Eq '^run-[0-9]{8}-[0-9]{6}-[a-z0-9]{6}$'; then
    echo "AI_RUN_ID имеет неверный формат" >&2
    exit 2
  fi

  SHORT_SHA="${AI_COMMIT_SHA:0:12}"
  ARTIFACT_VERSION="${GITHUB_RUN_NUMBER}-${SHORT_SHA}"
  TEST_IMAGE="ai-test:${ARTIFACT_VERSION}"
  RUNTIME_IMAGE="ai-runtime:${ARTIFACT_VERSION}"
  NETWORK_NAME="ai-scan-${GITHUB_RUN_NUMBER}-${SHORT_SHA}"
  APP_CONTAINER="ai-app-${GITHUB_RUN_NUMBER}-${SHORT_SHA}"

  PACKAGE_NAME="$(jq -r '.artifacts_upload.package_name' "$POLICY_FILE")"
  ARTIFACT_OWNER="$CI_ARTIFACT_OWNER"

  if ! printf '%s' "$ARTIFACT_OWNER" | grep -Eq '^[A-Za-z0-9_.-]+$'; then
    echo "CI_ARTIFACT_OWNER имеет неверный формат" >&2
    exit 2
  fi

  ARTIFACT_BASE="${CI_GITEA_URL%/}/api/packages/${ARTIFACT_OWNER}/generic/${PACKAGE_NAME}/${ARTIFACT_VERSION}"
}

run_unit_tests() {
  say "1/4 — Unit-тесты"

  local build_exit

  set +e
  docker build \
    --build-arg "PYTHON_BASE_IMAGE=${PYTHON_BASE_IMAGE}" \
    --target test \
    --file "$PROFILE_DOCKERFILE" \
    --tag "$TEST_IMAGE" \
    "$ROOT_DIR" \
    2>&1 | tee "$ARTIFACTS_DIR/unit-build.log"
  build_exit=${PIPESTATUS[0]}
  set -e

  if [ "$build_exit" -ne 0 ]; then
    UNIT_EXIT="$build_exit"
    if looks_like_network_failure "$ARTIFACTS_DIR/unit-build.log"; then
      UNIT_STATUS="infra_error"
    else
      UNIT_STATUS="$(classify_exit "$build_exit")"
    fi
    printf '%s\n' "$UNIT_EXIT" > "$ARTIFACTS_DIR/unit.exit"
    return 0
  fi

  set +e
  docker run --rm \
    --volume "$ARTIFACTS_DIR:/artifacts:rw" \
    "$TEST_IMAGE" \
    python -m pytest -q --junitxml=/artifacts/pytest.xml \
    2>&1 | tee "$ARTIFACTS_DIR/pytest.log"
  UNIT_EXIT=${PIPESTATUS[0]}
  set -e

  UNIT_STATUS="$(classify_exit "$UNIT_EXIT")"

  if [ "$UNIT_EXIT" -eq 0 ] && [ ! -s "$ARTIFACTS_DIR/pytest.xml" ]; then
    UNIT_EXIT=90
    UNIT_STATUS="infra_error"
    echo "pytest завершился с code 0, но pytest.xml отсутствует" >&2
  fi

  printf '%s\n' "$UNIT_EXIT" > "$ARTIFACTS_DIR/unit.exit"
}

run_semgrep() {
  say "2/4 — Статический анализ Semgrep"

  set +e
  docker run --rm \
    --volume "$ROOT_DIR:/src:ro" \
    --volume "$ARTIFACTS_DIR:/out:rw" \
    --workdir /src \
    "$SEMGREP_IMAGE" \
    semgrep scan \
      --config auto \
      --exclude artifacts \
      --json \
      --output /out/semgrep.json \
      . \
    2>&1 | tee "$ARTIFACTS_DIR/semgrep.log"
  SEMGREP_EXIT=${PIPESTATUS[0]}
  set -e

  if [ -s "$ARTIFACTS_DIR/semgrep.json" ] && \
     jq -e '.results | type == "array"' "$ARTIFACTS_DIR/semgrep.json" >/dev/null 2>&1; then
    SEMGREP_FINDINGS="$(jq '.results | length' "$ARTIFACTS_DIR/semgrep.json")"
  else
    SEMGREP_FINDINGS=0
  fi

  if [ "$SEMGREP_EXIT" -ne 0 ]; then
    if looks_like_network_failure "$ARTIFACTS_DIR/semgrep.log"; then
      SEMGREP_STATUS="infra_error"
    else
      SEMGREP_STATUS="$(classify_exit "$SEMGREP_EXIT")"
    fi
  elif [ ! -s "$ARTIFACTS_DIR/semgrep.json" ]; then
    SEMGREP_EXIT=90
    SEMGREP_STATUS="infra_error"
  elif jq -e '.static_analysis.semgrep.block_on_any_finding == true' "$POLICY_FILE" >/dev/null && \
       [ "$SEMGREP_FINDINGS" -gt 0 ]; then
    SEMGREP_STATUS="failed"
  else
    SEMGREP_STATUS="passed"
  fi

  printf '%s\n' "$SEMGREP_EXIT" > "$ARTIFACTS_DIR/semgrep.exit"
  printf '%s\n' "$SEMGREP_FINDINGS" > "$ARTIFACTS_DIR/semgrep.count"
}

run_runtime_smoke() {
  say "3/4 — Сборка и проверка запуска приложения"

  local build_exit
  local health_path
  local attempt
  local curl_exit

  health_path="$(jq -r '.runtime_smoke.health_path' "$POLICY_FILE")"

  set +e
  docker build \
    --build-arg "PYTHON_BASE_IMAGE=${PYTHON_BASE_IMAGE}" \
    --target runtime \
    --file "$PROFILE_DOCKERFILE" \
    --tag "$RUNTIME_IMAGE" \
    "$ROOT_DIR" \
    2>&1 | tee "$ARTIFACTS_DIR/runtime-build.log"
  build_exit=${PIPESTATUS[0]}
  set -e

  if [ "$build_exit" -ne 0 ]; then
    RUNTIME_EXIT="$build_exit"
    if looks_like_network_failure "$ARTIFACTS_DIR/runtime-build.log"; then
      RUNTIME_STATUS="infra_error"
    else
      RUNTIME_STATUS="$(classify_exit "$build_exit")"
    fi
    printf '%s\n' "$RUNTIME_EXIT" > "$ARTIFACTS_DIR/runtime.exit"
    return 0
  fi

  set +e
  docker network create "$NETWORK_NAME" > "$ARTIFACTS_DIR/network-create.log" 2>&1
  RUNTIME_EXIT=$?
  set -e

  if [ "$RUNTIME_EXIT" -ne 0 ]; then
    RUNTIME_STATUS="infra_error"
    printf '%s\n' "$RUNTIME_EXIT" > "$ARTIFACTS_DIR/runtime.exit"
    return 0
  fi

  set +e
  docker run --detach \
    --name "$APP_CONTAINER" \
    --network "$NETWORK_NAME" \
    --network-alias app \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    "$RUNTIME_IMAGE" \
    > "$ARTIFACTS_DIR/runtime-container-id.txt" \
    2> "$ARTIFACTS_DIR/runtime-start.log"
  RUNTIME_EXIT=$?
  set -e

  if [ "$RUNTIME_EXIT" -ne 0 ]; then
    RUNTIME_STATUS="$(classify_exit "$RUNTIME_EXIT")"
    printf '%s\n' "$RUNTIME_EXIT" > "$ARTIFACTS_DIR/runtime.exit"
    return 0
  fi

  RUNTIME_EXIT=1

  for attempt in $(seq 1 30); do
    set +e
    docker run --rm \
      --network "$NETWORK_NAME" \
      "$CURL_IMAGE" \
      --fail --silent --show-error \
      "http://app:8000${health_path}" \
      > "$ARTIFACTS_DIR/health.json" \
      2> "$ARTIFACTS_DIR/health-last-error.log"
    curl_exit=$?
    set -e

    if [ "$curl_exit" -eq 0 ]; then
      RUNTIME_EXIT=0
      RUNTIME_STATUS="passed"
      break
    fi

    if [ "$curl_exit" -eq 125 ]; then
      RUNTIME_EXIT=125
      RUNTIME_STATUS="infra_error"
      break
    fi

    sleep 2
  done

  if [ "$RUNTIME_EXIT" -ne 0 ] && [ "$RUNTIME_STATUS" != "infra_error" ]; then
    RUNTIME_STATUS="failed"
  fi

  docker logs "$APP_CONTAINER" > "$ARTIFACTS_DIR/runtime.log" 2>&1 || true
  printf '%s\n' "$RUNTIME_EXIT" > "$ARTIFACTS_DIR/runtime.exit"
}

run_zap() {
  say "4/4 — Динамический анализ OWASP ZAP Baseline"

  if [ "$RUNTIME_STATUS" != "passed" ]; then
    ZAP_EXIT=125
    ZAP_STATUS="not_run"
    printf '%s\n' "$ZAP_EXIT" > "$ARTIFACTS_DIR/zap.exit"
    printf '%s\n' 'not_run_due_to_runtime_failure' > "$ARTIFACTS_DIR/zap.log"
    return 0
  fi

  set +e
  docker run --rm \
    --network "$NETWORK_NAME" \
    --volume "$ARTIFACTS_DIR:/zap/wrk:rw" \
    "$ZAP_IMAGE" \
    zap-baseline.py \
      -t http://app:8000 \
      -J zap.json \
      -r zap.html \
      -w zap.md \
      -T 5 \
    2>&1 | tee "$ARTIFACTS_DIR/zap.log"
  ZAP_EXIT=${PIPESTATUS[0]}
  set -e

  if [ -s "$ARTIFACTS_DIR/zap.json" ]; then
    ZAP_ALERTS="$(jq '[.site[]?.alerts[]?] | length' "$ARTIFACTS_DIR/zap.json" 2>/dev/null || echo 0)"
  else
    ZAP_ALERTS=0
  fi

  if [ "$ZAP_EXIT" -eq 0 ]; then
    ZAP_STATUS="passed"
  elif jq -e --argjson code "$ZAP_EXIT" \
       '.dynamic_analysis.zap_baseline.warning_exit_codes | index($code) != null' \
       "$POLICY_FILE" >/dev/null; then
    ZAP_STATUS="warning"
  elif [ "$ZAP_EXIT" -eq 125 ] || [ "$ZAP_EXIT" -eq 126 ] || [ "$ZAP_EXIT" -eq 127 ]; then
    ZAP_STATUS="infra_error"
  else
    ZAP_STATUS="failed"
  fi

  printf '%s\n' "$ZAP_EXIT" > "$ARTIFACTS_DIR/zap.exit"
  printf '%s\n' "$ZAP_ALERTS" > "$ARTIFACTS_DIR/zap.count"
}

upload_one() {
  local file_name="$1"

  curl --fail-with-body --silent --show-error \
    --user "${CI_GITEA_USER}:${CI_GITEA_TOKEN}" \
    --upload-file "$ARTIFACTS_DIR/$file_name" \
    "${ARTIFACT_BASE}/${file_name}"
}

upload_raw_artifacts() {
  say "Публикация первичных артефактов в Gitea Generic Packages"

  local file_name
  local raw_files=(
    unit-build.log
    pytest.log
    pytest.xml
    unit.exit
    semgrep.log
    semgrep.json
    semgrep.exit
    semgrep.count
    runtime-build.log
    network-create.log
    runtime-container-id.txt
    runtime-start.log
    runtime.log
    runtime.exit
    health.json
    health-last-error.log
    zap.log
    zap.json
    zap.html
    zap.md
    zap.exit
    zap.count
  )

  UPLOAD_EXIT=0

  for file_name in "${raw_files[@]}"; do
    [ -f "$ARTIFACTS_DIR/$file_name" ] || continue

    if ! upload_one "$file_name"; then
      echo "Не удалось опубликовать: $file_name" >&2
      UPLOAD_EXIT=1
    fi
  done

  if [ "$UPLOAD_EXIT" -eq 0 ]; then
    UPLOAD_STATUS="passed"
  else
    UPLOAD_STATUS="failed"
  fi
}

append_finding() {
  local current="$1"
  local tool="$2"
  local rule_id="$3"
  local severity="$4"
  local blocking="$5"
  local path="$6"
  local line="$7"
  local message="$8"
  local fingerprint="$9"

  jq -cn \
    --argjson current "$current" \
    --arg tool "$tool" \
    --arg rule_id "$rule_id" \
    --arg severity "$severity" \
    --argjson blocking "$blocking" \
    --arg path "$path" \
    --argjson line "$line" \
    --arg message "$message" \
    --arg fingerprint "$fingerprint" \
    '$current + [{
      tool: $tool,
      rule_id: $rule_id,
      severity: $severity,
      blocking: $blocking,
      path: $path,
      line: $line,
      message: $message,
      fingerprint: $fingerprint
    }]'
}

calculate_quality() {
  local findings='[]'
  local semgrep_findings='[]'

  BLOCKING_COUNT=0

  if [ -s "$ARTIFACTS_DIR/semgrep.json" ] && \
     jq -e '.results | type == "array"' "$ARTIFACTS_DIR/semgrep.json" >/dev/null 2>&1; then
    semgrep_findings="$(jq -c '[.results[]? |
      ((.check_id // "unknown") | tostring) as $rule |
      ((.path // "") | tostring | sub("^/src/"; "") | sub("^\\./"; "")) as $path |
      ((.start.line // 0) | tonumber) as $line |
      (((.extra.severity // "unknown") | tostring | ascii_downcase)) as $raw_severity |
      {
        tool: "semgrep",
        rule_id: $rule,
        severity: (
          if $raw_severity == "error" then "high"
          elif $raw_severity == "warning" then "medium"
          else $raw_severity
          end
        ),
        blocking: true,
        path: $path,
        line: $line,
        message: ((.extra.message // "Semgrep finding") | tostring),
        fingerprint: (
          "semgrep|" + $rule + "|" + $path + "|" + ($line | tostring)
        )
      }
    ]' "$ARTIFACTS_DIR/semgrep.json")"
  fi

  findings="$semgrep_findings"

  if [ "$UNIT_STATUS" != "passed" ]; then
    findings="$(append_finding "$findings" pytest stage_failed high true '' 0 \
      "Unit stage: ${UNIT_STATUS}; exit=${UNIT_EXIT}" \
      'pytest|stage_failed')"
  fi

  if [ "$SEMGREP_STATUS" != "passed" ] && \
     [ "$(jq 'length' <<<"$semgrep_findings")" -eq 0 ]; then
    findings="$(append_finding "$findings" semgrep stage_error high true '' 0 \
      "Semgrep stage: ${SEMGREP_STATUS}; exit=${SEMGREP_EXIT}" \
      'semgrep|stage_error')"
  fi

  if [ "$RUNTIME_STATUS" != "passed" ]; then
    findings="$(append_finding "$findings" runtime_smoke stage_failed high true '' 0 \
      "Runtime smoke stage: ${RUNTIME_STATUS}; exit=${RUNTIME_EXIT}" \
      'runtime_smoke|stage_failed')"
  fi

  if [ "$ZAP_STATUS" = "failed" ] || [ "$ZAP_STATUS" = "infra_error" ] || [ "$ZAP_STATUS" = "not_run" ]; then
    findings="$(append_finding "$findings" zap stage_failed high true '' 0 \
      "ZAP stage: ${ZAP_STATUS}; exit=${ZAP_EXIT}" \
      'zap|stage_failed')"
  fi

  printf '%s\n' "$findings" > "$ARTIFACTS_DIR/findings.json"

  BLOCKING_COUNT="$(jq '[.[] | select(.blocking == true)] | length' "$ARTIFACTS_DIR/findings.json")"

  if [ "$BLOCKING_COUNT" -eq 0 ]; then
    QUALITY_PASSED=true
  else
    QUALITY_PASSED=false
  fi
}

build_ci_summary() {
  say "Формирование ci-summary.json"

  local overall_status

  if [ "$QUALITY_PASSED" = true ] && [ "$UPLOAD_STATUS" = "passed" ]; then
    overall_status="passed"
  else
    overall_status="failed"
  fi

  jq -n \
    --arg repository "$GITHUB_REPOSITORY" \
    --arg artifact_owner "$ARTIFACT_OWNER" \
    --arg artifact_package "$PACKAGE_NAME" \
    --arg artifact_base "$ARTIFACT_BASE" \
    --arg branch "$AI_BRANCH" \
    --arg commit_sha "$AI_COMMIT_SHA" \
    --arg run_id "$AI_RUN_ID" \
    --arg context_version "$AI_CONTEXT_VERSION" \
    --arg artifact_version "$ARTIFACT_VERSION" \
    --arg implementation_profile "python-fastapi-3.12" \
    --arg overall_status "$overall_status" \
    --arg unit_status "$UNIT_STATUS" \
    --arg semgrep_status "$SEMGREP_STATUS" \
    --arg runtime_status "$RUNTIME_STATUS" \
    --arg zap_status "$ZAP_STATUS" \
    --arg publication_status "$UPLOAD_STATUS" \
    --argjson run_number "$GITHUB_RUN_NUMBER" \
    --argjson pr_number "$AI_PR_NUMBER" \
    --argjson repair_attempt "$AI_REPAIR_ATTEMPT" \
    --argjson unit_exit "$UNIT_EXIT" \
    --argjson semgrep_exit "$SEMGREP_EXIT" \
    --argjson semgrep_findings "$SEMGREP_FINDINGS" \
    --argjson runtime_exit "$RUNTIME_EXIT" \
    --argjson zap_exit "$ZAP_EXIT" \
    --argjson zap_alerts "$ZAP_ALERTS" \
    --argjson blocking_count "$BLOCKING_COUNT" \
    --argjson quality_passed "$QUALITY_PASSED" \
    --slurpfile findings "$ARTIFACTS_DIR/findings.json" \
    '{
      schema_version: "2.0",
      repository: $repository,
      branch: $branch,
      commit_sha: $commit_sha,
      action_run_number: $run_number,
      workflow_context: {
        run_id: $run_id,
        pr_number: $pr_number,
        context_version: $context_version,
        repair_attempt: $repair_attempt
      },
      implementation_profile: $implementation_profile,
      artifact: {
        owner: $artifact_owner,
        package: $artifact_package,
        version: $artifact_version,
        base_url: $artifact_base,
        publication_status: $publication_status
      },
      scope: {
        unit_tests: true,
        static_analysis: ["semgrep"],
        dynamic_analysis: ["owasp-zap-baseline"],
        fuzzing: false,
        talos_deployment: false
      },
      overall_status: $overall_status,
      quality_gate: {
        passed: $quality_passed,
        blocking_count: $blocking_count
      },
      stages: [
        {
          name: "pytest",
          category: "unit",
          status: $unit_status,
          exit_code: $unit_exit,
          artifact: "pytest.xml"
        },
        {
          name: "semgrep",
          category: "static",
          status: $semgrep_status,
          exit_code: $semgrep_exit,
          finding_count: $semgrep_findings,
          artifact: "semgrep.json"
        },
        {
          name: "runtime_smoke",
          category: "runtime",
          status: $runtime_status,
          exit_code: $runtime_exit,
          artifact: "health.json"
        },
        {
          name: "zap_baseline",
          category: "dynamic",
          status: $zap_status,
          exit_code: $zap_exit,
          alert_count: $zap_alerts,
          artifacts: ["zap.json", "zap.html", "zap.md"]
        }
      ],
      findings: $findings[0]
    }' > "$ARTIFACTS_DIR/ci-summary.json.tmp"

  jq -e '
    .schema_version == "2.0" and
    (.repository | type == "string") and
    (.branch | type == "string") and
    (.commit_sha | test("^[0-9a-fA-F]{40,64}$")) and
    (.action_run_number | type == "number") and
    (.workflow_context.run_id | test("^run-[0-9]{8}-[0-9]{6}-[a-z0-9]{6}$")) and
    (.workflow_context.pr_number | type == "number") and
    (.workflow_context.pr_number > 0) and
    (.workflow_context.context_version | type == "string") and
    (.workflow_context.context_version | length > 0) and
    (.workflow_context.repair_attempt | type == "number") and
    (.workflow_context.repair_attempt >= 0) and
    (.artifact.version | type == "string") and
    (.scope.fuzzing == false) and
    (.quality_gate.passed | type == "boolean") and
    (.quality_gate.blocking_count | type == "number") and
    (.stages | length == 4) and
    ([.stages[].name] | index("schemathesis") == null) and
    (.findings | type == "array")
  ' "$ARTIFACTS_DIR/ci-summary.json.tmp" >/dev/null

  mv "$ARTIFACTS_DIR/ci-summary.json.tmp" "$ARTIFACTS_DIR/ci-summary.json"
}

build_test_report() {
  say "Формирование отдельного test-report.md"

  cat > "$ARTIFACTS_DIR/test-report.md" <<EOF
# Отчёт о тестировании и анализе безопасности

## Идентификация запуска

| Поле | Значение |
|---|---|
| Репозиторий | ${GITHUB_REPOSITORY} |
| Ветка | ${AI_BRANCH} |
| Commit SHA | ${AI_COMMIT_SHA} |
| Gitea Actions run | ${GITHUB_RUN_NUMBER} |
| Run ID | ${AI_RUN_ID} |
| PR | #${AI_PR_NUMBER} |
| Development context | ${AI_CONTEXT_VERSION} |
| Repair attempt that produced this head | ${AI_REPAIR_ATTEMPT} |
| Implementation profile | python-fastapi-3.12 |
| Версия пакета артефактов | ${ARTIFACT_VERSION} |

## Область проверки

- Unit-тестирование: pytest.
- Статический анализ исходного кода: Semgrep.
- Проверка сборки и запуска runtime-образа.
- Динамический анализ работающего HTTP-приложения: OWASP ZAP Baseline.
- Фаззинг: не выполнялся и отключён политикой.
- Развёртывание в Talos: не входит в этот тестовый запуск.

## Результаты

| Этап | Статус | Exit code | Результат |
|---|---|---:|---|
| Unit-тесты | ${UNIT_STATUS} | ${UNIT_EXIT} | pytest.xml и pytest.log |
| Semgrep | ${SEMGREP_STATUS} | ${SEMGREP_EXIT} | Findings: ${SEMGREP_FINDINGS} |
| Runtime smoke | ${RUNTIME_STATUS} | ${RUNTIME_EXIT} | health.json и runtime.log |
| OWASP ZAP Baseline | ${ZAP_STATUS} | ${ZAP_EXIT} | Alerts: ${ZAP_ALERTS} |

## Quality gate

- Пройден: ${QUALITY_PASSED}
- Блокирующих результатов: ${BLOCKING_COUNT}
- Публикация первичных артефактов: ${UPLOAD_STATUS}

## Артефакты

| Файл | Назначение | Адрес |
|---|---|---|
| ci-summary.json | Машиночитаемая сводка | ${ARTIFACT_BASE}/ci-summary.json |
| artifact-manifest.json | Контрольные суммы и размеры | ${ARTIFACT_BASE}/artifact-manifest.json |
| pytest.xml | JUnit-результаты unit-тестов | ${ARTIFACT_BASE}/pytest.xml |
| pytest.log | Журнал pytest | ${ARTIFACT_BASE}/pytest.log |
| semgrep.json | Результаты статического анализа | ${ARTIFACT_BASE}/semgrep.json |
| semgrep.log | Журнал Semgrep | ${ARTIFACT_BASE}/semgrep.log |
| health.json | Ответ runtime health check | ${ARTIFACT_BASE}/health.json |
| runtime.log | Журнал приложения | ${ARTIFACT_BASE}/runtime.log |
| zap.json | Машиночитаемый отчёт ZAP | ${ARTIFACT_BASE}/zap.json |
| zap.html | HTML-отчёт ZAP | ${ARTIFACT_BASE}/zap.html |
| zap.md | Markdown-отчёт ZAP | ${ARTIFACT_BASE}/zap.md |
| zap.log | Журнал ZAP | ${ARTIFACT_BASE}/zap.log |

## Интерпретация статусов

- passed — этап выполнен успешно;
- warning — обнаружены неблокирующие предупреждения;
- failed — тест или security gate завершился неуспешно;
- infra_error — этап не дал достоверного результата из-за инфраструктурной ошибки;
- not_run — этап не запускался из-за отсутствия необходимого предыдущего результата.

## Ограничения отчёта

Этот документ подтверждает только фактический запуск перечисленных этапов для
указанного commit SHA. Он не подтверждает нормативное соответствие, отсутствие
всех уязвимостей или успешное развёртывание в Talos.
EOF
}

build_artifact_manifest() {
  say "Формирование artifact-manifest.json"

  local entries='[]'
  local file_path
  local file_name
  local sha256
  local size

  for file_path in "$ARTIFACTS_DIR"/*; do
    [ -f "$file_path" ] || continue

    file_name="$(basename "$file_path")"

    if [ "$file_name" = "artifact-manifest.json" ]; then
      continue
    fi

    sha256="$(sha256sum "$file_path" | awk '{print $1}')"
    size="$(wc -c < "$file_path" | tr -d ' ')"

    entries="$(jq -cn \
      --argjson current "$entries" \
      --arg name "$file_name" \
      --arg sha256 "$sha256" \
      --argjson size "$size" \
      '$current + [{name:$name, sha256:$sha256, size_bytes:$size}]')"
  done

  jq -n \
    --arg repository "$GITHUB_REPOSITORY" \
    --arg commit_sha "$AI_COMMIT_SHA" \
    --arg run_id "$AI_RUN_ID" \
    --arg context_version "$AI_CONTEXT_VERSION" \
    --arg artifact_version "$ARTIFACT_VERSION" \
    --argjson pr_number "$AI_PR_NUMBER" \
    --argjson repair_attempt "$AI_REPAIR_ATTEMPT" \
    --argjson files "$entries" \
    '{
      schema_version: "1.0",
      repository: $repository,
      commit_sha: $commit_sha,
      run_id: $run_id,
      pr_number: $pr_number,
      context_version: $context_version,
      repair_attempt: $repair_attempt,
      artifact_version: $artifact_version,
      files: $files
    }' > "$ARTIFACTS_DIR/artifact-manifest.json"
}

upload_final_documents() {
  say "Публикация итоговой сводки и документов"

  local file_name
  local final_files=(
    findings.json
    ci-summary.json
    test-report.md
    artifact-manifest.json
  )

  for file_name in "${final_files[@]}"; do
    if ! upload_one "$file_name"; then
      echo "Не удалось опубликовать итоговый файл: $file_name" >&2
      UPLOAD_EXIT=1
      UPLOAD_STATUS="failed"
    fi
  done

  echo "AI_ARTIFACT_OWNER=${ARTIFACT_OWNER}"
  echo "AI_ARTIFACT_PACKAGE=${PACKAGE_NAME}"
  echo "AI_ARTIFACT_VERSION=${ARTIFACT_VERSION}"
  echo "AI_ARTIFACT_BASE=${ARTIFACT_BASE}"
}

quality_gate() {
  say "Quality gate"

  local failed=0

  if jq -e '.unit_tests.required == true' "$POLICY_FILE" >/dev/null && \
     [ "$UNIT_STATUS" != "passed" ]; then
    echo "FAIL: unit-тесты (${UNIT_STATUS})"
    failed=1
  fi

  if jq -e '.static_analysis.semgrep.required == true' "$POLICY_FILE" >/dev/null && \
     [ "$SEMGREP_STATUS" != "passed" ]; then
    echo "FAIL: Semgrep (${SEMGREP_STATUS})"
    failed=1
  fi

  if jq -e '.runtime_smoke.required == true' "$POLICY_FILE" >/dev/null && \
     [ "$RUNTIME_STATUS" != "passed" ]; then
    echo "FAIL: runtime smoke (${RUNTIME_STATUS})"
    failed=1
  fi

  if jq -e '.dynamic_analysis.zap_baseline.required == true' "$POLICY_FILE" >/dev/null; then
    if [ "$ZAP_STATUS" = "warning" ] && \
       jq -e '.dynamic_analysis.zap_baseline.warnings_block == false' "$POLICY_FILE" >/dev/null; then
      echo "WARN: OWASP ZAP обнаружил неблокирующие предупреждения"
    elif [ "$ZAP_STATUS" != "passed" ]; then
      echo "FAIL: OWASP ZAP (${ZAP_STATUS})"
      failed=1
    fi
  fi

  if jq -e '.artifacts_upload.required == true' "$POLICY_FILE" >/dev/null && \
     [ "$UPLOAD_STATUS" != "passed" ]; then
    echo "FAIL: публикация артефактов (${UPLOAD_STATUS})"
    failed=1
  fi

  if [ "$failed" -ne 0 ]; then
    echo "Quality gate не пройден. Используйте test-report.md и ci-summary.json."
    return 1
  fi

  echo "Quality gate пройден."
}

main() {
  validate_inputs
  prepare_workspace

  run_unit_tests
  run_semgrep
  run_runtime_smoke
  run_zap

  upload_raw_artifacts
  calculate_quality
  build_ci_summary
  build_test_report
  build_artifact_manifest
  upload_final_documents
  quality_gate
}

main "$@"
