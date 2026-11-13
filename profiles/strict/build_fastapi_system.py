from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_w1 import validate_built_workflow


ROOT = Path(__file__).resolve().parent
WORKFLOWS = ROOT / "workflows"
OUTPUT_NAMES = {
    "01": "01-requirements-fastapi-v5.json",
    "02": "02-architecture-fastapi-v5.json",
    "03": "03-implementation-fastapi-v5.json",
    "04": "04-ci-repair-fastapi-v5.json",
}
INSTRUCT_MODEL = "sim-qwen25-instruct:14b"
CODER_MODEL = "sim-qwen25-coder:14b"
MODEL_CONTEXT_TOKENS = 30720
DEVELOPER_MAX_OUTPUT_TOKENS = 16384
GENERATION_MAX_PAYLOAD_CHARS = 55000
REPOSITORY_CONTEXT_MAX_FILE_CHARS = 20000
REPOSITORY_CONTEXT_MAX_TOTAL_CHARS = 30000
ARCHITECTURE_TARGET_CHARS = 18000
ARCHITECTURE_HARD_MAX_CHARS = 22000


def load_workflow(prefix: str) -> dict[str, Any]:
    path = WORKFLOWS / OUTPUT_NAMES[prefix]
    if not path.is_file():
        raise RuntimeError(f"Отсутствует канонический workflow: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("state"), dict):
        raise RuntimeError(f"{path.name}: неверная структура export")
    if value.get("version") != "5.0":
        raise RuntimeError(f"{path.name}: version должна быть 5.0")
    return value


def block_values(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = workflow.get("state", {}).get("blocks", {})
    if not isinstance(blocks, dict):
        raise RuntimeError("state.blocks должен быть объектом")
    return list(blocks.values())


def named_block(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [item for item in block_values(workflow) if item.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"{name}: найдено блоков {len(matches)}")
    return matches[0]


def harden_language_guards(workflows: dict[str, dict[str, Any]]) -> None:
    w3_validator = named_block(workflows["03"], "Validate Generated Files")
    code = str(w3_validator["subBlocks"]["code"]["value"])
    marker = "Обнаружены китайские иероглифы в файле"
    if marker not in code:
        needle = """  if (content.length > maxFileChars) {
    errors.push(
      `Файл превышает лимит ${maxFileChars} символов: ${path}`
    );
  }
"""
        addition = needle + """
  if (/[\\u3400-\\u9fff]/u.test(content)) {
    errors.push(`Обнаружены китайские иероглифы в файле: ${path}`);
  }
  if (/<\\/?think>/iu.test(content)) {
    errors.push(`Обнаружен think tag в файле: ${path}`);
  }
"""
        if needle not in code:
            raise RuntimeError("Validate Generated Files: не найдена точка language guard")
        w3_validator["subBlocks"]["code"]["value"] = code.replace(needle, addition, 1)

    for validator_name in ("Validate Draft Revision", "Validate Final Revision"):
        item = named_block(workflows["04"], validator_name)
        code = str(item["subBlocks"]["code"]["value"])
        if marker in code:
            continue
        needle = """  if (content.length > 20000) {
    errors.push(
      `Содержимое файла слишком большое: ${path}`
    );
    continue;
  }
"""
        addition = needle + """
  if (/[\\u3400-\\u9fff]/u.test(content)) {
    errors.push(`Обнаружены китайские иероглифы в файле: ${path}`);
    continue;
  }
  if (/<\\/?think>/iu.test(content)) {
    errors.push(`Обнаружен think tag в файле: ${path}`);
    continue;
  }
"""
        if needle not in code:
            raise RuntimeError(f"{validator_name}: не найдена точка language guard")
        item["subBlocks"]["code"]["value"] = code.replace(needle, addition, 1)

    for prefix in ("03", "04"):
        path = WORKFLOWS / OUTPUT_NAMES[prefix]
        path.write_text(
            json.dumps(workflows[prefix], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )


def tune_resource_limits(workflows: dict[str, dict[str, Any]]) -> None:
    """Keep the single-call generator below the measured 16 GB VRAM boundary."""
    for prefix in ("02", "03"):
        catalog = named_block(workflows[prefix], "Implementation Profile Catalog")
        catalog_code = str(catalog["subBlocks"]["code"]["value"])
        catalog_code = catalog_code.replace(
            "max_payload_chars: 65000",
            f"max_payload_chars: {GENERATION_MAX_PAYLOAD_CHARS}",
        )
        catalog_code = catalog_code.replace(
            "max_payload_chars: 55000",
            f"max_payload_chars: {GENERATION_MAX_PAYLOAD_CHARS}",
        )
        catalog["subBlocks"]["code"]["value"] = catalog_code

    developer = named_block(workflows["03"], "Developer")
    developer["subBlocks"]["maxTokens"]["value"] = str(DEVELOPER_MAX_OUTPUT_TOKENS)
    messages = developer["subBlocks"].get("messages", {}).get("value", [])
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            message["content"] = message["content"].replace(
                "65000", str(GENERATION_MAX_PAYLOAD_CHARS)
            )

    # The architect returns Markdown rather than a structured object. Keep a
    # lower target in the prompt and a slightly larger deterministic safety
    # ceiling in the validator. This tolerates normal model verbosity without
    # silently truncating a complete architecture document.
    architect = named_block(workflows["02"], "Solution Architect")
    architect_messages = architect["subBlocks"].get("messages", {}).get("value", [])
    target_markers = (
        "Верни русский Markdown до 12000 символов",
        f"Верни русский Markdown до {ARCHITECTURE_TARGET_CHARS} символов",
    )
    target_replaced = False
    for message in architect_messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            continue
        content = message["content"]
        if target_markers[0] in content:
            content = content.replace(target_markers[0], target_markers[1], 1)
        if target_markers[1] in content:
            target_replaced = True
        message["content"] = content
    if not target_replaced:
        raise RuntimeError("Solution Architect: не найден целевой лимит Markdown")

    architecture_validator = named_block(
        workflows["02"], "Validate Architecture Output"
    )
    validator_code = str(architecture_validator["subBlocks"]["code"]["value"])
    validator_code = validator_code.replace(
        "document.length > 12000",
        f"document.length > {ARCHITECTURE_HARD_MAX_CHARS}",
    ).replace(
        "Архитектура превышает 12000 символов",
        f"Архитектура превышает {ARCHITECTURE_HARD_MAX_CHARS} символов",
    )
    if (
        f"document.length > {ARCHITECTURE_HARD_MAX_CHARS}" not in validator_code
        or f"Архитектура превышает {ARCHITECTURE_HARD_MAX_CHARS} символов"
        not in validator_code
    ):
        raise RuntimeError("Validate Architecture Output: лимит не обновлён")
    architecture_validator["subBlocks"]["code"]["value"] = validator_code


def align_cross_workflow_contracts(workflows: dict[str, dict[str, Any]]) -> None:
    """Keep consumer validators aligned with the artifact versions producers emit."""
    w1_approved = named_block(workflows["01"], "Build Approved Result")
    w1_code = str(w1_approved["subBlocks"]["code"]["value"])
    if "schema_version: '3.0'" not in w1_code:
        raise RuntimeError("Workflow 01: approved requirements schema_version должна быть 3.0")

    w2_validator = named_block(workflows["02"], "Validate Requirements Input")
    code = str(w2_validator["subBlocks"]["code"]["value"])
    old = "artifact.schema_version !== '2.0'"
    current = "artifact.schema_version !== '3.0'"
    if current not in code:
        if old not in code:
            raise RuntimeError("Workflow 02: не найден schema_version validator требований")
        code = code.replace(old, current, 1)
        w2_validator["subBlocks"]["code"]["value"] = code


def harden_downstream_workflows(workflows: dict[str, dict[str, Any]]) -> None:
    """Make downstream recovery paths safe for SIM and bound LLM context."""
    # Workflow 02: make the closed quality gate explicit in the HITL form. A
    # human approval intentionally cannot override a failed architecture review.
    approval = named_block(workflows["02"], "Architecture Approval")
    input_fields = approval["subBlocks"]["inputFormat"]["value"]
    decision = next(item for item in input_fields if item.get("name") == "decision")
    decision["description"] = (
        "approve доступен только при review_passed=true; иначе выберите revise или reject"
    )
    comments = next(item for item in input_fields if item.get("name") == "comments")
    comments["description"] = (
        "Обязательно для revise/reject; при failed quality gate перечислите исправления"
    )
    builder_fields = approval["subBlocks"]["builderData"]["value"]
    if not any(item.get("name") == "approval_available" for item in builder_fields):
        builder_fields.extend(
            [
                {
                    "id": "91eff2ab-25b2-4394-b42d-b71f63e7252d",
                    "name": "approval_available",
                    "type": "string",
                    "value": "<validatearchitecturereview.result.review.passed>",
                    "collapsed": False,
                },
                {
                    "id": "27ce52b8-e8c3-42e5-a879-a77aca493976",
                    "name": "required_action",
                    "type": "string",
                    "value": (
                        "Если approval_available=false, approve будет отклонён. "
                        "Выберите revise и опишите исправления либо reject."
                    ),
                    "collapsed": False,
                },
            ]
        )

    for check_name in (
        "Check Architecture Publication",
        "Check Architecture Revision Publication",
    ):
        publication_check = named_block(workflows["02"], check_name)
        publication_code = str(publication_check["subBlocks"]["code"]["value"])
        publication_check["subBlocks"]["code"]["value"] = publication_code.replace(
            "[200, 201, 204]", "[200, 201, 204, 409]"
        )

    # Workflow 03: a GET for a missing concrete branch returns 404, and SIM
    # terminates the API block before a following Condition can recover. Listing
    # branches keeps the expected "not found yet" state on an HTTP 200 path.
    target_branch = named_block(workflows["03"], "Get Target Branch")
    target_branch["subBlocks"]["url"]["value"] = (
        "{{GITEA_URL}}/api/v1/repos/"
        "<validateimplementationinput.result.owner>/"
        "<validateimplementationinput.result.repo>/branches"
    )
    target_branch["subBlocks"]["params"]["value"] = [
        {
            "id": "90c4830e-c8f5-4d3c-984a-023808a835af",
            "cells": {"Key": "page", "Value": "1"},
        },
        {
            "id": "bb24a594-034e-4edb-a6e4-6603fdf99a89",
            "cells": {"Key": "limit", "Value": "100"},
        },
    ]
    target_branch["subBlocks"]["retries"]["value"] = "2"

    branch_exists = named_block(workflows["03"], "Target Branch Exists")
    conditions = json.loads(branch_exists["subBlocks"]["conditions"]["value"])
    conditions[0]["value"] = (
        "Array.isArray(<gettargetbranch.data>) && "
        "<gettargetbranch.data>.some((item) => "
        "String(item?.name ?? '') === "
        "String(<validateimplementationinput.result.branch> ?? ''))"
    )
    branch_exists["subBlocks"]["conditions"]["value"] = json.dumps(
        conditions, ensure_ascii=False, separators=(",", ":")
    )

    check_branch = named_block(workflows["03"], "Check Created Branch")
    check_branch["subBlocks"]["code"]["value"] = """const listed = <gettargetbranch.data>;
const expectedName = String(<validateimplementationinput.result.branch> ?? '');
const existingBranch = Array.isArray(listed)
  ? listed.find((item) => String(item?.name ?? '') === expectedName)
  : null;
const existing = Boolean(existingBranch);
const selected = existing ? existingBranch : <getcreatedbranch.data>;
const status = existing ? Number(<gettargetbranch.status>) : Number(<getcreatedbranch.status>);
const actualName = String(selected?.name ?? '');
const commitSha = String(selected?.commit?.id ?? '');
return {
  valid: status === 200 && expectedName.length > 0 && actualName === expectedName && /^[0-9a-f]{40}$/i.test(commitSha),
  existing,
  branch: actualName,
  commit_sha: commitSha,
  status
};"""

    create_branch = named_block(workflows["03"], "Create Branch")
    create_branch["subBlocks"]["body"]["value"] = """{
  "new_branch_name": "<validateimplementationinput.result.branch>",
  "old_ref_name": "<validateimplementationinput.result.base_branch>"
}"""

    create_pr = named_block(workflows["03"], "Create PR")
    create_pr["subBlocks"]["body"]["value"] = str(
        create_pr["subBlocks"]["body"]["value"]
    ).replace('"base": "main"', '"base": "<validateimplementationinput.result.base_branch>"')

    repository_context = named_block(workflows["03"], "Build Repository Context")
    context_code = str(repository_context["subBlocks"]["code"]["value"])
    context_code = context_code.replace(
        "content.length > 200000",
        f"content.length > {REPOSITORY_CONTEXT_MAX_FILE_CHARS}",
    )
    context_code = context_code.replace(
        "totalChars > 600000",
        f"totalChars > {REPOSITORY_CONTEXT_MAX_TOTAL_CHARS}",
    )
    context_code = context_code.replace(
        "repository context exceeds 600000 characters",
        f"repository context exceeds {REPOSITORY_CONTEXT_MAX_TOTAL_CHARS} characters",
    )
    repository_context["subBlocks"]["code"]["value"] = context_code

    developer = named_block(workflows["03"], "Developer")
    developer_messages = developer["subBlocks"]["messages"]["value"]
    user_message = next(item for item in developer_messages if item.get("role") == "user")
    duplicate = (
        "APPROVED ARCHITECTURE ARTIFACT:\n"
        "<validateimplementationinput.result.artifact>\n\n"
    )
    user_message["content"] = str(user_message["content"]).replace(duplicate, "")
    response_format = json.loads(developer["subBlocks"]["responseFormat"]["value"])
    response_format["schema"]["properties"]["files"]["maxItems"] = 15
    developer["subBlocks"]["responseFormat"]["value"] = json.dumps(
        response_format, ensure_ascii=False, indent=2
    )

    contract_publication = named_block(workflows["03"], "Check Contract Publication")
    contract_publication["subBlocks"]["code"]["value"] = """const status = Number(<publishdevelopmentcontract.status>);
const valid = [200, 201, 204, 409].includes(status);
return {
  valid,
  status,
  newly_created: status !== 409,
  package_owner: <preparedevelopmentcontract.result.package_owner>,
  package_name: <preparedevelopmentcontract.result.package_name>,
  package_version: <preparedevelopmentcontract.result.package_version>,
  error: valid ? '' : `Gitea package upload returned HTTP ${status}`
};"""

    # Workflow 04: use the branch-name form documented by Gitea and verify the
    # dispatch response before reporting that a new CI run was scheduled.
    dispatch = named_block(workflows["04"], "Trigger Recheck CI")
    dispatch["subBlocks"]["body"]["value"] = str(
        dispatch["subBlocks"]["body"]["value"]
    ).replace(
        '"ref": "refs/heads/<validateinput.result.branch>"',
        '"ref": "<validateinput.result.branch>"',
    )

    w4_blocks = workflows["04"]["state"]["blocks"]
    check_id = "c0decfce-5725-49bd-a421-1e37e7557644"
    if check_id not in w4_blocks:
        w4_blocks[check_id] = {
            "id": check_id,
            "type": "function",
            "name": "Check Recheck CI Dispatch",
            "position": {"x": 14670, "y": -38},
            "subBlocks": {
                "code": {
                    "id": "code",
                    "type": "code",
                    "value": """const status = Number(<triggerrecheckci.status>);
const data = <triggerrecheckci.data>;
if (![200, 204].includes(status)) {
  throw new Error(`Повторный CI не поставлен в очередь: HTTP ${status}`);
}
const runId = status === 200
  ? Number(data?.id ?? data?.workflow_run_id ?? 0)
  : 0;
if (status === 200 && (!Number.isInteger(runId) || runId < 1)) {
  throw new Error('Gitea вернула HTTP 200 без идентификатора повторного CI run');
}
return {
  valid: true,
  status,
  workflow_run_id: runId || null,
  run_url: String(data?.html_url ?? data?.run_url ?? '')
};""",
                },
                "language": {
                    "id": "language",
                    "type": "dropdown",
                    "value": "javascript",
                },
            },
            "outputs": {
                "result": {"type": "json", "description": "Function result"},
                "stdout": {"type": "string", "description": "Function stdout"},
            },
            "enabled": True,
            "horizontalHandles": True,
            "height": 0,
            "advancedMode": False,
            "triggerMode": False,
            "data": {},
            "locked": False,
        }

    response = named_block(workflows["04"], "Revision Written")
    response["subBlocks"]["data"]["value"] = """{
  "repair": <verifyrevisionwrites.result>,
  "ci_recheck": <checkrecheckcidispatch.result>
}"""

    trigger_id = dispatch["id"]
    response_id = response["id"]
    edges = workflows["04"]["state"]["edges"]
    direct = next(
        (
            edge
            for edge in edges
            if edge.get("source") == trigger_id and edge.get("target") == response_id
        ),
        None,
    )
    if direct:
        direct["target"] = check_id
    if not any(
        edge.get("source") == check_id and edge.get("target") == response_id
        for edge in edges
    ):
        edges.append(
            {
                "id": "454bd97c-00a7-48ea-967b-1c8b5fecc9d2",
                "source": check_id,
                "target": response_id,
                "sourceHandle": "source",
                "targetHandle": "target",
                "type": "default",
                "data": {},
            }
        )

    # All API calls are local/self-hosted and should fail deterministically
    # instead of waiting on a platform default with unknown duration.
    for prefix in ("02", "03", "04"):
        for item in block_values(workflows[prefix]):
            if item.get("type") != "api":
                continue
            timeout = item.get("subBlocks", {}).get("timeout")
            if timeout and timeout.get("value") in (None, ""):
                timeout["value"] = "30000"


def validate_api_baseline(prefix: str, workflow: dict[str, Any]) -> None:
    raw = json.dumps(workflow, ensure_ascii=False)
    forbidden = ("demo-python-cli", "python-cli-3.12", "qwen3-coder-next")
    leaked = [item for item in forbidden if item in raw]
    if leaked:
        raise RuntimeError(f"Workflow {prefix}: запрещённые ссылки {leaked}")
    if "python-fastapi-3.12" not in raw or "labadmin/demo-fastapi" not in raw:
        raise RuntimeError(f"Workflow {prefix}: отсутствует FastAPI production profile")

    blocks = block_values(workflow)
    if len([item for item in blocks if item.get("type") == "start_trigger"]) != 1:
        raise RuntimeError(f"Workflow {prefix}: нужен ровно один Start")
    ids = {str(item.get("id", "")) for item in blocks}
    if len(ids) != len(blocks) or "" in ids:
        raise RuntimeError(f"Workflow {prefix}: повторяющиеся или пустые block IDs")
    for edge in workflow.get("state", {}).get("edges", []):
        if edge.get("source") not in ids or edge.get("target") not in ids:
            raise RuntimeError(f"Workflow {prefix}: оборванное edge")

    allowed_models = {INSTRUCT_MODEL, CODER_MODEL}
    for item in blocks:
        if item.get("type") != "agent":
            continue
        sub = item.get("subBlocks", {})
        model = sub.get("model", {}).get("value")
        if model not in allowed_models:
            raise RuntimeError(f"Workflow {prefix}, {item.get('name')}: неверная модель")
        if sub.get("thinkingLevel", {}).get("value") != "none":
            raise RuntimeError(f"Workflow {prefix}, {item.get('name')}: thinking включён")
        reasoning = sub.get("reasoningEffort")
        if reasoning and reasoning.get("value") != "none":
            raise RuntimeError(f"Workflow {prefix}, {item.get('name')}: reasoning включён")

    for item in blocks:
        if item.get("type") != "api":
            continue
        sub = item.get("subBlocks", {})
        if str(sub.get("method", {}).get("value", "")).upper() == "POST":
            if int(sub.get("retries", {}).get("value", 0)) != 0:
                raise RuntimeError(f"Workflow {prefix}, {item.get('name')}: POST retries != 0")


def write_manifest() -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": "1.0",
        "bundle_version": "5.0",
        "bundle": "fastapi-production-v5",
        "generated_at": now,
        "application_profile": "python-fastapi-3.12",
        "repository_allowlist": ["labadmin/demo-fastapi"],
        "models": {
            "requirements_and_review": INSTRUCT_MODEL,
            "architecture_and_code": CODER_MODEL,
            "reasoning": "disabled",
            "context_tokens": MODEL_CONTEXT_TOKENS,
        },
        "generation_limits": {
            "max_files": 15,
            "max_file_chars": 20000,
            "max_payload_chars": GENERATION_MAX_PAYLOAD_CHARS,
        },
        "ci_revision_context_limits": {
            "max_files": 5,
            "max_file_chars": 20000,
            "max_total_chars": 30000,
        },
        "implementation_repository_context_limits": {
            "max_file_chars": REPOSITORY_CONTEXT_MAX_FILE_CHARS,
            "max_total_chars": REPOSITORY_CONTEXT_MAX_TOTAL_CHARS,
        },
        "max_requirements_repairs": 5,
        "max_ci_repairs": 5,
        "workflows": [f"workflows/{OUTPUT_NAMES[prefix]}" for prefix in OUTPUT_NAMES],
        "workflow_change_scope": {
            "01": "substantial: structured requirements plus async checkpoint state machine",
            "02": "substantial: fixed FastAPI profile and closed quality gate",
            "03": "substantial: API-only generation and resumable branch/PR",
            "04": "substantial: API-only repair with preserved dispatch context",
        },
        "required_sim_environment": [
            "GITEA_URL",
            "GITEA_TOKEN",
            "SIM_INTERNAL_URL",
            "SIM_WORKFLOW01_ID",
            "SIM_WORKFLOW02_ID",
            "SIM_WORKFLOW03_ID",
            "SIM_WORKFLOW_API_KEY",
        ],
        "required_gitea_actions_variables": [
            "AI_GITEA_URL",
            "AI_GITEA_USER",
            "AI_ARTIFACT_OWNER",
            "AI_ARTIFACT_PACKAGE",
            "AI_CONTEXT_OWNER",
            "AI_CONTEXT_PACKAGE",
            "AI_REVISE_ENABLED",
            "AI_REVISE_DRY_RUN",
            "AI_REVISE_CALLBACK_REQUIRED",
            "AI_MAX_REPAIR_ATTEMPTS",
            "SIM_INTERNAL_URL",
            "SIM_WORKFLOW04_ID",
        ],
        "required_gitea_actions_secrets": [
            "AI_GITEA_TOKEN",
            "SIM_WORKFLOW_API_KEY",
        ],
        "security": {
            "literal_secrets_in_exports": False,
            "non_idempotent_api_retries": 0,
            "manual_merge_required": True,
        },
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return manifest


def main() -> None:
    workflows = {prefix: load_workflow(prefix) for prefix in OUTPUT_NAMES}
    align_cross_workflow_contracts(workflows)
    tune_resource_limits(workflows)
    harden_downstream_workflows(workflows)
    harden_language_guards(workflows)
    for prefix, workflow in workflows.items():
        path = WORKFLOWS / OUTPUT_NAMES[prefix]
        path.write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    for prefix, workflow in workflows.items():
        validate_api_baseline(prefix, workflow)
    validate_built_workflow(workflows["01"])
    manifest = write_manifest()
    print(
        json.dumps(
            {
                "valid": True,
                "output": str(ROOT),
                "workflows": [Path(item).name for item in manifest["workflows"]],
                "source": "self-contained canonical API exports",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
