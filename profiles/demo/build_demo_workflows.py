from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT.parent / "strict"
SOURCE_WORKFLOWS = SOURCE_ROOT / "workflows"
WORKFLOWS = ROOT / "workflows"
MODEL = "qwen3-coder-next:latest"

REQUIRED_DOCUMENTATION_PATHS = [
    "docs/USER_GUIDE.md",
    "docs/ADMIN_GUIDE.md",
    "docs/TECHNICAL_GUIDE.md",
]

SOURCE_FILES = {
    "01": "01-requirements-fastapi-v5.json",
    "02": "02-architecture-fastapi-v5.json",
    "03": "03-implementation-fastapi-v5.json",
    "04": "04-ci-repair-fastapi-v5.json",
}

OUTPUT_FILES = {
    "01": "01-requirements-demo-simple.json",
    "02": "02-architecture-demo-simple.json",
    "03": "03-implementation-demo-simple.json",
    "04": "04-ci-repair-demo-simple.json",
}


def uid() -> str:
    return str(uuid.uuid4())


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load_sources() -> dict[str, dict[str, Any]]:
    return {
        key: json.loads((SOURCE_WORKFLOWS / value).read_text(encoding="utf-8"))
        for key, value in SOURCE_FILES.items()
    }


SOURCES = load_sources()


def source_block(prefix: str, name: str) -> dict[str, Any]:
    blocks = SOURCES[prefix]["state"]["blocks"].values()
    matches = [item for item in blocks if item.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"{prefix}/{name}: expected one template, got {len(matches)}")
    return matches[0]


def clone(prefix: str, template: str, name: str | None = None) -> dict[str, Any]:
    item = copy.deepcopy(source_block(prefix, template))
    item["id"] = uid()
    item["name"] = name or template
    item["position"] = {"x": 0, "y": 0}
    item["enabled"] = True
    return item


def set_start(item: dict[str, Any], fields: list[dict[str, Any]]) -> None:
    normalized = []
    for field in fields:
        normalized.append(
            {
                "id": uid(),
                "name": field["name"],
                "type": field.get("type", "string"),
                "value": field.get("value", ""),
                "collapsed": field.get("collapsed", True),
                "description": field.get("description", ""),
            }
        )
    item["subBlocks"]["inputFormat"]["value"] = normalized


def set_function(item: dict[str, Any], code: str) -> None:
    item["subBlocks"]["code"]["value"] = code.strip() + "\n"


def set_agent(
    item: dict[str, Any],
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int,
) -> None:
    sub = item["subBlocks"]
    sub["model"]["value"] = MODEL
    sub["messages"]["value"] = [
        {"role": "system", "content": system.strip()},
        {"role": "user", "content": user.strip()},
    ]
    sub["maxTokens"]["value"] = str(max_tokens)
    sub["responseFormat"]["value"] = json.dumps(schema, ensure_ascii=False, indent=2)
    if "thinkingLevel" in sub:
        sub["thinkingLevel"]["value"] = "none"
    if "reasoningEffort" in sub:
        sub["reasoningEffort"]["value"] = "none"
    if "memoryType" in sub:
        sub["memoryType"]["value"] = "none"
    if "temperature" in sub:
        sub["temperature"]["value"] = 0.2


def set_condition(
    item: dict[str, Any], expressions: list[tuple[str, str]]
) -> dict[str, str]:
    options = []
    handles: dict[str, str] = {}
    for index, (title, expression) in enumerate(expressions):
        suffix = "if" if index == 0 else "else" if title == "else" else f"else-if-{index}"
        option_id = f"{item['id']}-{suffix}"
        # SIM stores the option id without a prefix, but the corresponding
        # React Flow source handle is named `condition-<option id>`.
        handles[title] = f"condition-{option_id}"
        options.append(
            {
                "id": option_id,
                "title": title,
                "value": expression,
                "showTags": False,
                "searchTerm": "",
                "showEnvVars": False,
                "cursorPosition": len(expression),
                "activeSourceBlockId": None,
            }
        )
    item["subBlocks"]["conditions"]["value"] = json.dumps(
        options, ensure_ascii=False, separators=(",", ":")
    )
    return handles


def set_human(
    item: dict[str, Any],
    builder_fields: list[tuple[str, str, bool]],
    *,
    decision_description: str,
) -> None:
    item["subBlocks"]["builderData"]["value"] = [
        {
            "id": uid(),
            "name": name,
            "type": "string",
            "value": value,
            "collapsed": collapsed,
        }
        for name, value, collapsed in builder_fields
    ]
    item["subBlocks"]["inputFormat"]["value"] = [
        {
            "id": uid(),
            "name": "decision",
            "type": "string",
            "value": "",
            "collapsed": False,
            "description": decision_description,
        },
        {
            "id": uid(),
            "name": "comments",
            "type": "string",
            "value": "",
            "collapsed": True,
            "description": "Комментарий обязателен только для reject",
        },
    ]


def set_response(item: dict[str, Any], data: str, status: int) -> None:
    item["subBlocks"]["data"]["value"] = data
    item["subBlocks"]["status"]["value"] = str(status)
    item["subBlocks"]["dataMode"]["value"] = "json"
    if "builderData" in item["subBlocks"]:
        item["subBlocks"]["builderData"]["value"] = []


def set_api(
    item: dict[str, Any],
    *,
    method: str,
    url: str,
    body: str | None = None,
    sim: bool = False,
    params: list[tuple[str, str]] | None = None,
) -> None:
    sub = item["subBlocks"]
    sub["method"]["value"] = method
    sub["url"]["value"] = url
    sub["body"]["value"] = body
    headers = [("Content-Type", "application/json")]
    if sim:
        headers.extend(
            [
                ("x-api-key", "{{SIM_WORKFLOW_API_KEY}}"),
                ("X-Execution-Mode", "async"),
            ]
        )
    else:
        headers = [
            ("Authorization", "token {{GITEA_TOKEN}}"),
            ("Accept", "application/json"),
        ] + ([ ("Content-Type", "application/json") ] if method != "GET" else [])
    sub["headers"]["value"] = [
        {"id": uid(), "cells": {"Key": key, "Value": value}}
        for key, value in headers
    ]
    sub["params"]["value"] = [
        {"id": uid(), "cells": {"Key": key, "Value": value}}
        for key, value in (params or [])
    ]
    sub["retries"]["value"] = "0"
    sub["timeout"]["value"] = "30000"
    if "retryNonIdempotent" in sub:
        sub["retryNonIdempotent"]["value"] = False


def make_workflow(
    prefix: str,
    blocks: list[dict[str, Any]],
    edges: list[tuple[str, str, str | None]],
    *,
    name: str,
    description: str,
    condition_handles: dict[str, dict[str, str]],
    loops: list[tuple[str, str, str, int]] | None = None,
) -> dict[str, Any]:
    by_name = {item["name"]: item for item in blocks}
    if len(by_name) != len(blocks):
        raise RuntimeError(f"{prefix}: duplicate block names")
    for index, item in enumerate(blocks):
        item["position"] = {"x": 80 + (index % 10) * 430, "y": 80 + (index // 10) * 420}
    edge_values = []
    for source, target, route in edges:
        source_handle = "source"
        if route == "loop-end":
            source_handle = "loop-end-source"
        elif route:
            source_handle = condition_handles[source][route]
        edge_values.append(
            {
                "id": uid(),
                "source": by_name[source]["id"],
                "target": by_name[target]["id"],
                "sourceHandle": source_handle,
                "targetHandle": "target",
                "type": "default",
                "data": {},
            }
        )
    loop_values: dict[str, Any] = {}
    for loop_name, child_name, collection, count in loops or []:
        loop_block = by_name[loop_name]
        child_block = by_name[child_name]
        # Blocks registered in state.loops use coordinates local to the loop
        # container. Keeping the global grid position makes the imported node
        # appear outside the loop and can detach its visual connection in SIM.
        child_block["position"] = {"x": 120, "y": 80}
        # The cloned API node still points to the loop id from the source
        # workflow. SIM uses data.parentId (in addition to state.loops.nodes)
        # to decide whether the loop contains an executable block.
        child_block.setdefault("data", {})["parentId"] = loop_block["id"]
        child_block["data"]["extent"] = "parent"
        loop_block["data"].update(
            {
                "collection": collection,
                "count": count,
                "loopType": "forEach",
                "type": "subflowNode",
            }
        )
        loop_values[loop_block["id"]] = {
            "id": loop_block["id"],
            "nodes": [child_block["id"]],
            "iterations": count,
            "loopType": "forEach",
            "enabled": True,
            "forEachItems": collection,
            "whileCondition": "",
            "doWhileCondition": "",
        }
        edge_values.append(
            {
                "id": uid(),
                "source": loop_block["id"],
                "target": child_block["id"],
                "sourceHandle": "loop-start-source",
                "targetHandle": "target",
                "type": "default",
                "data": {},
            }
        )
    result = copy.deepcopy(SOURCES[prefix])
    result["version"] = "1.0"
    result["exportedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result["state"]["blocks"] = {item["id"]: item for item in blocks}
    result["state"]["edges"] = edge_values
    result["state"]["loops"] = loop_values
    result["state"]["parallels"] = {}
    result["state"]["variables"] = {}
    result["state"]["metadata"] = {
        "name": name,
        "description": description,
        "variant": "fastapi-demo-simple-v1",
        "profile_id": "python-fastapi-3.12",
        "target_repository": "labadmin/demo-fastapi",
        "model": MODEL,
        "thinking": "none",
    }
    return result


REQUIREMENTS_SCHEMA = {
    "name": "demo_requirements",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "maxLength": 2500},
            "functional_requirements": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "maxLength": 20},
                        "requirement": {"type": "string", "maxLength": 1400},
                        "acceptance": {"type": "string", "maxLength": 1400},
                    },
                    "required": ["id", "requirement", "acceptance"],
                },
            },
            "constraints": {
                "type": "array",
                "maxItems": 20,
                "items": {"type": "string", "maxLength": 1000},
            },
            "documentation_requirements": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "maxLength": 30},
                        "path": {"type": "string", "maxLength": 200},
                        "audience": {"type": "string", "maxLength": 300},
                        "content": {"type": "string", "maxLength": 1400},
                        "acceptance": {"type": "string", "maxLength": 1400},
                    },
                    "required": ["id", "path", "audience", "content", "acceptance"],
                },
            },
            "test_scenarios": {
                "type": "array",
                "maxItems": 30,
                "items": {"type": "string", "maxLength": 1200},
            },
            "open_questions": {
                "type": "array",
                "maxItems": 10,
                "items": {"type": "string", "maxLength": 800},
            },
        },
        "required": [
            "summary",
            "functional_requirements",
            "constraints",
            "documentation_requirements",
            "test_scenarios",
            "open_questions",
        ],
    },
}


ARCHITECTURE_SCHEMA = {
    "name": "demo_architecture",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "maxLength": 2500},
            "architecture": {"type": "string", "maxLength": 22000},
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "maxLength": 200},
                        "purpose": {"type": "string", "maxLength": 700},
                    },
                    "required": ["path", "purpose"],
                },
            },
            "test_strategy": {"type": "string", "maxLength": 4000},
            "risks": {
                "type": "array",
                "maxItems": 10,
                "items": {"type": "string", "maxLength": 800},
            },
        },
        "required": ["summary", "architecture", "files", "test_strategy", "risks"],
    },
}


FILES_SCHEMA = {
    "name": "demo_generated_files",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "maxLength": 2000},
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "maxLength": 200},
                        "content": {"type": "string", "maxLength": 30000},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "required": ["summary", "files"],
    },
}


CI_ANALYSIS_SCHEMA = {
    "name": "demo_ci_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {"type": "string", "enum": ["repair", "manual"]},
            "summary": {"type": "string", "maxLength": 2500},
            "files": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string", "maxLength": 200},
            },
            "instructions": {"type": "string", "maxLength": 4000},
        },
        "required": ["decision", "summary", "files", "instructions"],
    },
}


REVISION_SCHEMA = {
    "name": "demo_revision",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "maxLength": 2000},
            "files": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "maxLength": 200},
                        "content": {"type": "string", "maxLength": 20000},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "required": ["summary", "files"],
    },
}


def build_workflow_01() -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    handles: dict[str, dict[str, str]] = {}
    start = clone("01", "Start")
    set_start(
        start,
        [
            {"name": "user_request", "collapsed": False, "description": "Задача для FastAPI-приложения"},
            {"name": "target_owner", "value": "labadmin", "description": "Владелец Gitea-репозитория"},
            {"name": "target_repo", "value": "demo-fastapi", "description": "Репозиторий для демонстрации"},
            {"name": "base_branch", "value": "main"},
            {"name": "artifact_owner", "value": "labadmin"},
            {"name": "artifact_package", "value": "ai-demo-artifacts"},
        ],
    )
    blocks.append(start)

    init = clone("01", "Init Request", "Initialize Request")
    set_function(
        init,
        r"""
const request = String(<start.user_request> ?? '').trim();
const owner = String(<start.target_owner> ?? 'labadmin').trim();
const repo = String(<start.target_repo> ?? 'demo-fastapi').trim();
const baseBranch = String(<start.base_branch> ?? 'main').trim();
const artifactOwner = String(<start.artifact_owner> ?? 'labadmin').trim();
const artifactPackage = String(<start.artifact_package> ?? 'ai-demo-artifacts').trim();
const errors = [];
if (request.length < 20) errors.push('Опишите задачу минимум двадцатью символами');
if (request.length > 20000) errors.push('Задача превышает 20000 символов');
if (!/^[A-Za-z0-9_.-]{1,100}$/.test(owner) || !/^[A-Za-z0-9_.-]{1,100}$/.test(repo)) errors.push('Некорректный owner/repo');
if (!/^[A-Za-z0-9_.\/-]{1,100}$/.test(baseBranch)) errors.push('Некорректная base branch');
if (!/^[A-Za-z0-9_.-]{1,100}$/.test(artifactOwner) || !/^[A-Za-z0-9_.-]{1,100}$/.test(artifactPackage)) errors.push('Некорректный package owner/name');
const iso = new Date().toISOString();
const stamp = iso.slice(0,10).replace(/-/g,'') + '-' + iso.slice(11,19).replace(/:/g,'');
const suffix = Math.random().toString(36).slice(2,8).padEnd(6,'0');
return {valid: errors.length === 0, errors, user_request: request, run_id: `run-${stamp}-${suffix}`, target: {owner, repo, base_branch: baseBranch}, artifact_owner: artifactOwner, artifact_package: artifactPackage};
""",
    )
    blocks.append(init)
    condition = clone("01", "Input Valid")
    handles[condition["name"]] = set_condition(
        condition,
        [("if", "<initializerequest.result.valid> === true"), ("else", "")],
    )
    blocks.append(condition)
    invalid = clone("01", "Invalid Input")
    set_response(invalid, "<initializerequest.result>", 422)
    blocks.append(invalid)

    analyst = clone("01", "Requirements Analyst")
    set_agent(
        analyst,
        system="""
Ты аналитик требований демонстрационного FastAPI-проекта. Верни только JSON
Response Format. Сформулируй компактные, проверяемые требования без внутренней
архитектуры и без функций, которых нет в запросе. Python 3.12, FastAPI,
app.main:app, /health, OpenAPI, pytest и отсутствие секретов являются
ограничениями демонстрационного стенда. Полный комплект пользовательской и
эксплуатационной документации является обязательным результатом стенда даже
для короткого исходного запроса. В documentation_requirements создай ровно по
одному проверяемому требованию для каждого пути: docs/USER_GUIDE.md,
docs/ADMIN_GUIDE.md и docs/TECHNICAL_GUIDE.md. Техническое руководство должно
объединять описание API, архитектуры, структуры проекта, технологий и
тестирования. Требования к документам должны учитывать фактическую задачу, не
выдумывать окружение, секреты и уже выполненные проверки. Обычный текст пиши
по-русски.
""",
        user="""
RUN ID: <initializerequest.result.run_id>
TARGET: <initializerequest.result.target>

ЗАДАЧА:
<initializerequest.result.user_request>

Верни краткие требования, критерии приёмки, требования к трём обязательным
документам и тестовые сценарии.
""",
        schema=REQUIREMENTS_SCHEMA,
        max_tokens=8192,
    )
    blocks.append(analyst)
    validate = clone("01", "Render Initial Requirements", "Validate Requirements")
    set_function(
        validate,
        r"""
const requirements = {
  summary: String(<requirementsanalyst.summary> ?? '').trim(),
  functional_requirements: Array.isArray(<requirementsanalyst.functional_requirements>) ? <requirementsanalyst.functional_requirements> : [],
  constraints: Array.isArray(<requirementsanalyst.constraints>) ? <requirementsanalyst.constraints> : [],
  documentation_requirements: Array.isArray(<requirementsanalyst.documentation_requirements>) ? <requirementsanalyst.documentation_requirements> : [],
  test_scenarios: Array.isArray(<requirementsanalyst.test_scenarios>) ? <requirementsanalyst.test_scenarios> : [],
  open_questions: Array.isArray(<requirementsanalyst.open_questions>) ? <requirementsanalyst.open_questions> : []
};
const errors = [];
if (requirements.summary.length < 20) errors.push('Нет содержательного summary');
if (requirements.functional_requirements.length < 1) errors.push('Нет функциональных требований');
if (requirements.test_scenarios.length < 1) errors.push('Нет тестовых сценариев');
const requiredDocs=['docs/USER_GUIDE.md','docs/ADMIN_GUIDE.md','docs/TECHNICAL_GUIDE.md'];
const docs=new Map();
for(const item of requirements.documentation_requirements){const path=String(item?.path??'').trim();if(docs.has(path.toLowerCase()))errors.push(`Дубликат требования к документу: ${path}`);docs.set(path.toLowerCase(),item);if(String(item?.content??'').trim().length<40)errors.push(`Не описано содержание документа: ${path}`);if(String(item?.acceptance??'').trim().length<40)errors.push(`Нет проверяемой приёмки документа: ${path}`);}
for(const path of requiredDocs)if(!docs.has(path.toLowerCase()))errors.push(`Нет требования к обязательному документу: ${path}`);
if(requirements.documentation_requirements.length!==requiredDocs.length)errors.push('Нужно ровно три требования к документации');
return {valid: errors.length === 0, errors, requirements, context: <initializerequest.result>};
""",
    )
    blocks.append(validate)
    valid = clone("01", "Requirements Structurally Valid", "Requirements Valid")
    handles[valid["name"]] = set_condition(
        valid,
        [("if", "<validaterequirements.result.valid> === true"), ("else", "")],
    )
    blocks.append(valid)
    invalid_model = clone("01", "Invalid Input", "Invalid Requirements Output")
    set_response(invalid_model, "<validaterequirements.result>", 422)
    blocks.append(invalid_model)
    approval = clone("01", "Requirements Approval")
    set_human(
        approval,
        [
            ("run_id", "<validaterequirements.result.context.run_id>", True),
            ("requirements", "<validaterequirements.result.requirements>", False),
            ("instruction", "approve — продолжить; reject — остановить", False),
        ],
        decision_description="Только approve или reject",
    )
    blocks.append(approval)
    normalize = clone("01", "Normalize Decision")
    set_function(
        normalize,
        r"""
const decision = String(<requirementsapproval.decision> ?? '').trim().toLowerCase();
const comments = String(<requirementsapproval.comments> ?? '').trim();
const valid = ['approve','reject'].includes(decision) && (decision !== 'reject' || comments.length >= 3);
return {valid, decision, comments, error: valid ? '' : 'Допустимы approve или reject; для reject нужен комментарий'};
""",
    )
    blocks.append(normalize)
    decision = clone("01", "Decision")
    handles[decision["name"]] = set_condition(
        decision,
        [
            ("if", "<normalizedecision.result.valid> === false"),
            ("approve", "String(<normalizedecision.result.decision> ?? '') === 'approve'"),
            ("else", ""),
        ],
    )
    blocks.append(decision)
    invalid_decision = clone("01", "Invalid Decision")
    set_response(invalid_decision, "<normalizedecision.result>", 422)
    blocks.append(invalid_decision)
    rejected = clone("01", "Rejected")
    set_response(rejected, "<normalizedecision.result>", 200)
    blocks.append(rejected)
    build = clone("01", "Build Approved Result", "Build Requirements Artifact")
    set_function(
        build,
        r"""
const context = <validaterequirements.result.context>;
const file = 'requirements.json';
const ref = {owner: context.artifact_owner, package: context.artifact_package, version: context.run_id, file};
const artifact = {schema_version:'1.0', workflow_id:'01-requirements-demo', status:'approved', run_id:context.run_id, target:context.target, requirements:<validaterequirements.result.requirements>, source_request:context.user_request, approval:{decision:'approve', submitted_at:<requirementsapproval.submittedAt>}, artifact_ref:ref};
const trigger = {input:{artifact_owner:ref.owner, artifact_package:ref.package, artifact_version:ref.version, requirements_file:ref.file}};
return {artifact, artifact_ref:ref, artifact_json:JSON.stringify(artifact), trigger_json:JSON.stringify(trigger)};
""",
    )
    blocks.append(build)
    publish = clone("01", "Publish Requirements Artifact")
    set_api(
        publish,
        method="PUT",
        url="{{GITEA_URL}}/api/packages/<buildrequirementsartifact.result.artifact_ref.owner>/generic/<buildrequirementsartifact.result.artifact_ref.package>/<buildrequirementsartifact.result.artifact_ref.version>/<buildrequirementsartifact.result.artifact_ref.file>",
        body="<buildrequirementsartifact.result.artifact_json>",
    )
    blocks.append(publish)
    check_publish = clone("01", "Check Requirements Publication")
    set_function(
        check_publish,
        "const status=Number(<publishrequirementsartifact.status>); if(![200,201,204].includes(status)) throw new Error(`Gitea package upload failed: HTTP ${status}`); return {valid:true,status};",
    )
    blocks.append(check_publish)
    trigger = clone("01", "Trigger Workflow 02")
    set_api(
        trigger,
        method="POST",
        url="{{SIM_INTERNAL_URL}}/api/workflows/{{SIM_WORKFLOW02_ID}}/execute",
        body="<buildrequirementsartifact.result.trigger_json>",
        sim=True,
    )
    blocks.append(trigger)
    check_trigger = clone("01", "Check Workflow 02 Trigger")
    set_function(
        check_trigger,
        "const status=Number(<triggerworkflow02.status>); if(![200,201,202,204].includes(status)) throw new Error(`Workflow 02 dispatch failed: HTTP ${status}`); return {valid:true,status};",
    )
    blocks.append(check_trigger)
    approved = clone("01", "Approved")
    set_response(
        approved,
        "<buildrequirementsartifact.result>",
        200,
    )
    blocks.append(approved)

    edges = [
        ("Start", "Initialize Request", None),
        ("Initialize Request", "Input Valid", None),
        ("Input Valid", "Requirements Analyst", "if"),
        ("Input Valid", "Invalid Input", "else"),
        ("Requirements Analyst", "Validate Requirements", None),
        ("Validate Requirements", "Requirements Valid", None),
        ("Requirements Valid", "Requirements Approval", "if"),
        ("Requirements Valid", "Invalid Requirements Output", "else"),
        ("Requirements Approval", "Normalize Decision", None),
        ("Normalize Decision", "Decision", None),
        ("Decision", "Invalid Decision", "if"),
        ("Decision", "Build Requirements Artifact", "approve"),
        ("Decision", "Rejected", "else"),
        ("Build Requirements Artifact", "Publish Requirements Artifact", None),
        ("Publish Requirements Artifact", "Check Requirements Publication", None),
        ("Check Requirements Publication", "Trigger Workflow 02", None),
        ("Trigger Workflow 02", "Check Workflow 02 Trigger", None),
        ("Check Workflow 02 Trigger", "Approved", None),
    ]
    return make_workflow(
        "01",
        blocks,
        edges,
        name="01 — Требования FastAPI [demo simple]",
        description="Один LLM-вызов, ручное approve и автоматическая передача через Gitea Package.",
        condition_handles=handles,
    )


def build_workflow_02() -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    handles: dict[str, dict[str, str]] = {}
    start = clone("02", "Start")
    set_start(
        start,
        [
            {"name": "artifact_owner", "value": "labadmin"},
            {"name": "artifact_package", "value": "ai-demo-artifacts"},
            {"name": "artifact_version", "description": "run_id из Workflow 01"},
            {"name": "requirements_file", "value": "requirements.json"},
        ],
    )
    blocks.append(start)
    get_artifact = clone("02", "Get Requirements Artifact")
    set_api(
        get_artifact,
        method="GET",
        url="{{GITEA_URL}}/api/packages/<start.artifact_owner>/generic/<start.artifact_package>/<start.artifact_version>/<start.requirements_file>",
    )
    blocks.append(get_artifact)
    validate_input = clone("02", "Validate Requirements Input")
    set_function(
        validate_input,
        r"""
const errors=[];
let artifact=<getrequirementsartifact.data>;
if(Number(<getrequirementsartifact.status>)!==200) errors.push('Requirements artifact не получен');
for(let i=0;i<2 && typeof artifact==='string';i++){try{artifact=JSON.parse(artifact);}catch(_){errors.push('Requirements artifact не JSON');artifact=null;break;}}
if(artifact?.data && typeof artifact.data==='object') artifact=artifact.data;
if(!artifact || typeof artifact!=='object') errors.push('Requirements artifact отсутствует');
if(artifact && artifact.workflow_id!=='01-requirements-demo') errors.push('Неверный источник requirements');
if(artifact && artifact.status!=='approved') errors.push('Requirements не approved');
if(!/^run-\d{8}-\d{6}-[a-z0-9]{6}$/.test(String(artifact?.run_id??''))) errors.push('Некорректный run_id');
return {valid:errors.length===0,errors,artifact};
""",
    )
    blocks.append(validate_input)
    input_valid = clone("02", "Requirements Input Valid")
    handles[input_valid["name"]] = set_condition(
        input_valid,
        [("if", "<validaterequirementsinput.result.valid> === true"), ("else", "")],
    )
    blocks.append(input_valid)
    invalid_input = clone("02", "Invalid Requirements Input")
    set_response(invalid_input, "<validaterequirementsinput.result>", 422)
    blocks.append(invalid_input)
    architect = clone("02", "Solution Architect")
    set_agent(
        architect,
        system="""
Ты архитектор демонстрационного FastAPI-проекта. Верни только JSON Response
Format. На основании утверждённых требований подготовь компактную архитектуру
и полный список application-owned файлов. Профиль фиксирован: Python 3.12,
FastAPI, app.main:app, /health, /openapi.json, pytest. Не включай .gitea/**,
ci/**, secrets, .env, контейнерные и инфраструктурные файлы. План обязательно
включает app/__init__.py, app/main.py, requirements.txt,
requirements-dev.txt, хотя бы один tests/test_*.py и полный комплект
документации: docs/USER_GUIDE.md, docs/ADMIN_GUIDE.md и
docs/TECHNICAL_GUIDE.md. Техническое руководство объединяет API, архитектуру,
структуру проекта, технологии и тестирование. В purpose каждого документа
перечисли его фактическое содержание и аудиторию. Не добавляй бизнес-функции
без основания. Архитектура должна быть достаточной для генерации полного
запускаемого проекта и всей его документации, но без кода и без вымышленных
сведений об окружении. Не подгоняй repository plan под фиксированное количество
файлов: включи столько application-owned файлов, сколько действительно нужно.
""",
        user="""
TARGET: <validaterequirementsinput.result.artifact.target>
REQUIREMENTS: <validaterequirementsinput.result.artifact.requirements>

Сформируй архитектуру, тестовую стратегию и полный список необходимых файлов
без искусственного ограничения их количества. Все три обязательных документа
из требований должны присутствовать отдельными файлами.
""",
        schema=ARCHITECTURE_SCHEMA,
        max_tokens=12288,
    )
    blocks.append(architect)
    validate_arch = clone("02", "Validate Architecture Output", "Validate Architecture")
    set_function(
        validate_arch,
        r"""
const architecture={summary:String(<solutionarchitect.summary>??'').trim(),architecture:String(<solutionarchitect.architecture>??'').trim(),files:Array.isArray(<solutionarchitect.files>)?<solutionarchitect.files>:[],test_strategy:String(<solutionarchitect.test_strategy>??'').trim(),risks:Array.isArray(<solutionarchitect.risks>)?<solutionarchitect.risks>:[]};
const errors=[]; const seen=new Set(); const safe=/^(?!\/)(?!.*\.\.)(?!.*\\)[A-Za-z0-9._/-]+$/;
if(architecture.architecture.length<300) errors.push('Архитектура слишком короткая');
for(const item of architecture.files){const path=String(item?.path??'').trim();if(!safe.test(path)||/^(\.git|\.gitea|\.github|ci|k8s|secrets)\//i.test(path))errors.push(`Недопустимый path: ${path}`);if(seen.has(path.toLowerCase()))errors.push(`Дубликат path: ${path}`);seen.add(path.toLowerCase());}
for(const required of ['app/__init__.py','app/main.py','requirements.txt','requirements-dev.txt','docs/USER_GUIDE.md','docs/ADMIN_GUIDE.md','docs/TECHNICAL_GUIDE.md']) if(!seen.has(required.toLowerCase())) errors.push(`Нет обязательного файла: ${required}`);
if(!architecture.files.some(x=>String(x?.path??'').startsWith('tests/'))) errors.push('Нет тестового файла');
return {valid:errors.length===0,errors,architecture,requirements_artifact:<validaterequirementsinput.result.artifact>};
""",
    )
    blocks.append(validate_arch)
    arch_valid = clone("02", "Architecture Output Valid", "Architecture Valid")
    handles[arch_valid["name"]] = set_condition(
        arch_valid,
        [("if", "<validatearchitecture.result.valid> === true"), ("else", "")],
    )
    blocks.append(arch_valid)
    invalid_arch = clone("02", "Invalid Architecture Model Output", "Invalid Architecture")
    set_response(invalid_arch, "<validatearchitecture.result>", 422)
    blocks.append(invalid_arch)
    approval = clone("02", "Architecture Approval")
    set_human(
        approval,
        [
            ("run_id", "<validatearchitecture.result.requirements_artifact.run_id>", True),
            ("summary", "<validatearchitecture.result.architecture.summary>", False),
            ("architecture", "<validatearchitecture.result.architecture.architecture>", True),
            ("files", "<validatearchitecture.result.architecture.files>", False),
            ("instruction", "approve — продолжить; reject — остановить", False),
        ],
        decision_description="Только approve или reject",
    )
    blocks.append(approval)
    normalize = clone("02", "Normalize Architecture Decision", "Normalize Decision")
    set_function(
        normalize,
        r"""
const decision=String(<architectureapproval.decision>??'').trim().toLowerCase();const comments=String(<architectureapproval.comments>??'').trim();const valid=['approve','reject'].includes(decision)&&(decision!=='reject'||comments.length>=3);return {valid,decision,comments,error:valid?'':'Допустимы approve или reject; для reject нужен комментарий'};
""",
    )
    blocks.append(normalize)
    decision = clone("02", "Architecture Decision", "Decision")
    handles[decision["name"]] = set_condition(
        decision,
        [
            ("if", "<normalizedecision.result.valid> === false"),
            ("approve", "String(<normalizedecision.result.decision> ?? '') === 'approve'"),
            ("else", ""),
        ],
    )
    blocks.append(decision)
    invalid_decision = clone("02", "Invalid Architecture Decision", "Invalid Decision")
    set_response(invalid_decision, "<normalizedecision.result>", 422)
    blocks.append(invalid_decision)
    rejected = clone("02", "Architecture Rejected", "Rejected")
    set_response(rejected, "<normalizedecision.result>", 200)
    blocks.append(rejected)
    build = clone("02", "Build Architecture Result", "Build Architecture Artifact")
    set_function(
        build,
        r"""
const req=<validatearchitecture.result.requirements_artifact>;const value=<validatearchitecture.result.architecture>;const file='architecture.json';const ref={owner:String(<start.artifact_owner>),package:String(<start.artifact_package>),version:req.run_id,file};const artifact={schema_version:'1.0',workflow_id:'02-architecture-demo',status:'approved',run_id:req.run_id,target:req.target,requirements:req.requirements,architecture:value.architecture,architecture_summary:value.summary,repository_plan:{files:value.files},test_strategy:value.test_strategy,risks:value.risks,approval:{decision:'approve',submitted_at:<architectureapproval.submittedAt>},artifact_ref:ref};const trigger={input:{artifact_owner:ref.owner,artifact_package:ref.package,artifact_version:ref.version,architecture_file:ref.file,dry_run:false}};return {artifact,artifact_ref:ref,artifact_json:JSON.stringify(artifact),trigger_json:JSON.stringify(trigger)};
""",
    )
    blocks.append(build)
    publish = clone("02", "Publish Architecture Artifact")
    set_api(
        publish,
        method="PUT",
        url="{{GITEA_URL}}/api/packages/<buildarchitectureartifact.result.artifact_ref.owner>/generic/<buildarchitectureartifact.result.artifact_ref.package>/<buildarchitectureartifact.result.artifact_ref.version>/<buildarchitectureartifact.result.artifact_ref.file>",
        body="<buildarchitectureartifact.result.artifact_json>",
    )
    blocks.append(publish)
    check_publish = clone("02", "Check Architecture Publication")
    set_function(check_publish, "const status=Number(<publisharchitectureartifact.status>);if(![200,201,204].includes(status))throw new Error(`Architecture package upload failed: HTTP ${status}`);return {valid:true,status};")
    blocks.append(check_publish)
    trigger = clone("02", "Trigger Workflow 03")
    set_api(
        trigger,
        method="POST",
        url="{{SIM_INTERNAL_URL}}/api/workflows/{{SIM_WORKFLOW03_ID}}/execute",
        body="<buildarchitectureartifact.result.trigger_json>",
        sim=True,
    )
    blocks.append(trigger)
    check_trigger = clone("02", "Check Workflow 03 Trigger")
    set_function(check_trigger, "const status=Number(<triggerworkflow03.status>);if(![200,201,202,204].includes(status))throw new Error(`Workflow 03 dispatch failed: HTTP ${status}`);return {valid:true,status};")
    blocks.append(check_trigger)
    approved = clone("02", "Architecture Approved", "Approved")
    set_response(approved, "<buildarchitectureartifact.result>", 200)
    blocks.append(approved)
    edges = [
        ("Start", "Get Requirements Artifact", None),
        ("Get Requirements Artifact", "Validate Requirements Input", None),
        ("Validate Requirements Input", "Requirements Input Valid", None),
        ("Requirements Input Valid", "Solution Architect", "if"),
        ("Requirements Input Valid", "Invalid Requirements Input", "else"),
        ("Solution Architect", "Validate Architecture", None),
        ("Validate Architecture", "Architecture Valid", None),
        ("Architecture Valid", "Architecture Approval", "if"),
        ("Architecture Valid", "Invalid Architecture", "else"),
        ("Architecture Approval", "Normalize Decision", None),
        ("Normalize Decision", "Decision", None),
        ("Decision", "Invalid Decision", "if"),
        ("Decision", "Build Architecture Artifact", "approve"),
        ("Decision", "Rejected", "else"),
        ("Build Architecture Artifact", "Publish Architecture Artifact", None),
        ("Publish Architecture Artifact", "Check Architecture Publication", None),
        ("Check Architecture Publication", "Trigger Workflow 03", None),
        ("Trigger Workflow 03", "Check Workflow 03 Trigger", None),
        ("Check Workflow 03 Trigger", "Approved", None),
    ]
    return make_workflow(
        "02",
        blocks,
        edges,
        name="02 — Архитектура FastAPI [demo simple]",
        description="Один архитектор формирует архитектуру и repository plan без отдельного reviewer.",
        condition_handles=handles,
    )


def build_workflow_03() -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    handles: dict[str, dict[str, str]] = {}
    start = clone("03", "Start")
    set_start(
        start,
        [
            {"name": "artifact_owner", "value": "labadmin"},
            {"name": "artifact_package", "value": "ai-demo-artifacts"},
            {"name": "artifact_version", "description": "run_id из Workflow 01"},
            {"name": "architecture_file", "value": "architecture.json"},
            {"name": "dry_run", "type": "boolean", "value": False, "description": "true — не писать в Gitea"},
        ],
    )
    blocks.append(start)
    get_artifact = clone("03", "Get Architecture Artifact")
    set_api(
        get_artifact,
        method="GET",
        url="{{GITEA_URL}}/api/packages/<start.artifact_owner>/generic/<start.artifact_package>/<start.artifact_version>/<start.architecture_file>",
    )
    blocks.append(get_artifact)
    validate_input = clone("03", "Validate Implementation Input")
    set_function(
        validate_input,
        r"""
const errors=[];let artifact=<getarchitectureartifact.data>;
if(Number(<getarchitectureartifact.status>)!==200)errors.push('Architecture artifact не получен');
for(let i=0;i<2&&typeof artifact==='string';i++){try{artifact=JSON.parse(artifact);}catch(_){errors.push('Architecture artifact не JSON');artifact=null;break;}}
if(artifact?.data&&typeof artifact.data==='object')artifact=artifact.data;
if(!artifact||typeof artifact!=='object')errors.push('Architecture artifact отсутствует');
if(artifact&&artifact.workflow_id!=='02-architecture-demo')errors.push('Неверный источник architecture');
if(artifact&&artifact.status!=='approved')errors.push('Architecture не approved');
if(!Array.isArray(artifact?.repository_plan?.files))errors.push('Нет repository plan');
const runId=String(artifact?.run_id??'');if(!/^run-\d{8}-\d{6}-[a-z0-9]{6}$/.test(runId))errors.push('Некорректный run_id');
const owner=String(artifact?.target?.owner??''),repo=String(artifact?.target?.repo??''),baseBranch=String(artifact?.target?.base_branch??'');
if(!owner||!repo||!baseBranch)errors.push('Не задан target repository');
const branch=`ai/${runId}`;
return {valid:errors.length===0,errors,artifact,run_id:runId,owner,repo,base_branch:baseBranch,branch,branch_encoded:encodeURIComponent(branch),dry_run:Boolean(<start.dry_run>),artifact_ref:{owner:String(<start.artifact_owner>),package:String(<start.artifact_package>),version:String(<start.artifact_version>),file:String(<start.architecture_file>)}};
""",
    )
    blocks.append(validate_input)
    input_valid = clone("03", "Input Valid")
    handles[input_valid["name"]] = set_condition(input_valid, [("if", "<validateimplementationinput.result.valid> === true"), ("else", "")])
    blocks.append(input_valid)
    invalid_input = clone("03", "Invalid Implementation")
    set_response(invalid_input, "<validateimplementationinput.result>", 422)
    blocks.append(invalid_input)
    get_base = clone("03", "Get Base Branch")
    set_api(
        get_base,
        method="GET",
        url="{{GITEA_URL}}/api/v1/repos/<validateimplementationinput.result.owner>/<validateimplementationinput.result.repo>/branches/<validateimplementationinput.result.base_branch>",
    )
    blocks.append(get_base)
    get_branches = clone("03", "Get Target Branch", "List Branches")
    set_api(
        get_branches,
        method="GET",
        url="{{GITEA_URL}}/api/v1/repos/<validateimplementationinput.result.owner>/<validateimplementationinput.result.repo>/branches",
        params=[("page", "1"), ("limit", "100")],
    )
    blocks.append(get_branches)
    resolve_branch = clone("03", "Check Created Branch", "Resolve Branch")
    set_function(
        resolve_branch,
        r"""
const errors=[];const base=<getbasebranch.data>;const branches=<listbranches.data>;const target=String(<validateimplementationinput.result.branch>??'');
if(Number(<getbasebranch.status>)!==200||!base?.commit?.id)errors.push('Base branch не получена');
if(Number(<listbranches.status>)!==200||!Array.isArray(branches))errors.push('Список веток не получен');
const existing=Array.isArray(branches)?branches.find(x=>String(x?.name??'')===target):null;
return {valid:errors.length===0,errors,exists:Boolean(existing),branch:target,base_sha:String(base?.commit?.id??''),existing_sha:String(existing?.commit?.id??'')};
""",
    )
    blocks.append(resolve_branch)
    branch_valid = clone("03", "Branch Correct", "Branch Context Valid")
    handles[branch_valid["name"]] = set_condition(branch_valid, [("if", "<resolvebranch.result.valid> === true"), ("else", "")])
    blocks.append(branch_valid)
    branch_error = clone("03", "Branch Incorrect", "Branch Context Error")
    set_response(branch_error, "<resolvebranch.result>", 424)
    blocks.append(branch_error)
    exists = clone("03", "Target Branch Exists")
    handles[exists["name"]] = set_condition(exists, [("if", "<resolvebranch.result.exists> === true"), ("else", "")])
    blocks.append(exists)
    create_branch = clone("03", "Create Branch")
    set_api(
        create_branch,
        method="POST",
        url="{{GITEA_URL}}/api/v1/repos/<validateimplementationinput.result.owner>/<validateimplementationinput.result.repo>/branches",
        body="{\"new_branch_name\":\"<validateimplementationinput.result.branch>\",\"old_branch_name\":\"<validateimplementationinput.result.base_branch>\"}",
    )
    blocks.append(create_branch)
    check_create = clone("03", "Check Created Branch", "Check Branch Creation")
    set_function(check_create, "const status=Number(<createbranch.status>);if(![200,201].includes(status))throw new Error(`Create branch failed: HTTP ${status}`);return {valid:true,status};")
    blocks.append(check_create)
    get_working = clone("03", "Get Created Branch", "Get Working Branch")
    set_api(
        get_working,
        method="GET",
        url="{{GITEA_URL}}/api/v1/repos/<validateimplementationinput.result.owner>/<validateimplementationinput.result.repo>/branches/<validateimplementationinput.result.branch_encoded>",
    )
    blocks.append(get_working)
    get_tree = clone("03", "Get Target Branch Tree")
    set_api(
        get_tree,
        method="GET",
        url="{{GITEA_URL}}/api/v1/repos/<validateimplementationinput.result.owner>/<validateimplementationinput.result.repo>/git/trees/<getworkingbranch.data.commit.id>",
        params=[("recursive", "true")],
    )
    blocks.append(get_tree)
    split_plan = clone("03", "Prepare Writes", "Split Implementation Plan")
    set_function(
        split_plan,
        r"""
const plan=Array.isArray(<validateimplementationinput.result.artifact.repository_plan.files>)?<validateimplementationinput.result.artifact.repository_plan.files>:[];
const requiredDocs=['docs/USER_GUIDE.md','docs/ADMIN_GUIDE.md','docs/TECHNICAL_GUIDE.md'];
const docSet=new Set(requiredDocs.map(x=>x.toLowerCase()));
const documentationFiles=plan.filter(x=>docSet.has(String(x?.path??'').trim().toLowerCase()));
const testFiles=plan.filter(x=>String(x?.path??'').trim().toLowerCase().startsWith('tests/'));
const applicationFiles=plan.filter(x=>{const path=String(x?.path??'').trim().toLowerCase();return !docSet.has(path)&&!path.startsWith('tests/');});
const present=new Set(documentationFiles.map(x=>String(x?.path??'').trim().toLowerCase()));
const missing=requiredDocs.filter(x=>!present.has(x.toLowerCase()));
if(missing.length)throw new Error(`Architecture plan is missing documentation files: ${missing.join(', ')}`);
if(testFiles.length<1)throw new Error('Architecture plan does not contain tests');
return {application_files:applicationFiles,test_files:testFiles,documentation_files:documentationFiles,required_documentation_paths:requiredDocs};
""",
    )
    blocks.append(split_plan)
    developer = clone("03", "Developer")
    set_agent(
        developer,
        system="""
Ты разработчик демонстрационного FastAPI-проекта. Верни только JSON Response
Format с полным replacement content всех и только переданных application и
dependency файлов. Проект должен запускаться как app.main:app на Python 3.12 и
предоставлять /health и /openapi.json. Тесты и документацию создают отдельные
агенты. Не пиши .gitea/**, ci/**, .env и секреты. Не используй TODO, заглушки и
Markdown fences вокруг содержимого файлов. Не заявляй, что тесты выполнены.
""",
        user="""
REQUIREMENTS: <validateimplementationinput.result.artifact.requirements>
ARCHITECTURE: <validateimplementationinput.result.artifact.architecture>
TEST STRATEGY: <validateimplementationinput.result.artifact.test_strategy>
APPROVED APPLICATION FILES: <splitimplementationplan.result.application_files>
CURRENT TREE: <gettargetbranchtree.data.tree>

Верни каждый путь из APPROVED APPLICATION FILES ровно один раз и никаких
других файлов. Перед ответом сравни список возвращаемых путей с approved list.
""",
        schema=FILES_SCHEMA,
        max_tokens=16384,
    )
    blocks.append(developer)
    test_developer = clone("03", "Developer", "Test Developer")
    set_agent(
        test_developer,
        system="""
Ты разработчик автоматических тестов FastAPI-проекта. Верни только JSON Response
Format с полным replacement content всех и только переданных test files.
Создай запускаемые pytest-тесты по требованиям и test strategy, согласованные с
переданным application code. Не возвращай код приложения, зависимости или
документацию. Не используй TODO, заглушки, внешнюю сеть, реальные секреты и
Markdown fences. Не заявляй, что тесты уже выполнены.
""",
        user="""
REQUIREMENTS: <validateimplementationinput.result.artifact.requirements>
TEST STRATEGY: <validateimplementationinput.result.artifact.test_strategy>
APPROVED TEST FILES: <splitimplementationplan.result.test_files>
GENERATED APPLICATION FILES: <developer.files>

Верни каждый путь из APPROVED TEST FILES ровно один раз и никаких других
файлов. Перед ответом сравни список возвращаемых путей с approved list.
""",
        schema=FILES_SCHEMA,
        max_tokens=12288,
    )
    blocks.append(test_developer)
    writer = clone("03", "Developer", "Documentation Writer")
    set_agent(
        writer,
        system="""
Ты технический писатель FastAPI-проекта. Верни только JSON Response Format с
полным replacement content всех и только переданных documentation files.
Документы пиши по-русски, а команды, пути, имена endpoint и идентификаторы
оставляй в исходном виде. Документируй только поведение из требований,
архитектуры и плана: не выдумывай адреса, секреты, инфраструктуру, выполненные
тесты и возможности продукта. Если эксплуатационная функция неприменима,
напиши это явно и объясни причину.

USER_GUIDE должен описывать назначение продукта, подготовку, пользовательские
сценарии, примеры запросов/ответов и ошибки. ADMIN_GUIDE должен описывать
установку, конфигурацию, запуск и остановку, health-check, логи, обновление и
откат, резервное копирование при наличии сохраняемых данных, безопасность и
диагностику. TECHNICAL_GUIDE должен объединять описание API и моделей данных,
архитектуры и потоков, дерева проекта и ответственности файлов, технологий и
зависимостей, а также стратегии, команд и сценариев тестирования. Каждый
документ должен иметь содержательные Markdown-заголовки. Не используй TODO и
заглушки.
""",
        user="""
REQUIREMENTS: <validateimplementationinput.result.artifact.requirements>
DOCUMENTATION REQUIREMENTS: <validateimplementationinput.result.artifact.requirements.documentation_requirements>
ARCHITECTURE: <validateimplementationinput.result.artifact.architecture>
TEST STRATEGY: <validateimplementationinput.result.artifact.test_strategy>
APPROVED DOCUMENTATION FILES: <splitimplementationplan.result.documentation_files>

Верни полное, согласованное между файлами содержимое каждого документа.
""",
        schema=FILES_SCHEMA,
        max_tokens=16384,
    )
    blocks.append(writer)
    inspect_files = clone("03", "Validate Generated Files", "Inspect Generated Files")
    set_function(
        inspect_files,
        r"""
const plan=Array.isArray(<validateimplementationinput.result.artifact.repository_plan.files>)?<validateimplementationinput.result.artifact.repository_plan.files>:[];const approved=new Set(plan.map(x=>String(x?.path??'').trim()));const applicationApproved=new Set(<splitimplementationplan.result.application_files>.map(x=>String(x?.path??'').trim()));const testsApproved=new Set(<splitimplementationplan.result.test_files>.map(x=>String(x?.path??'').trim()));const docsApproved=new Set(<splitimplementationplan.result.documentation_files>.map(x=>String(x?.path??'').trim()));const groups=[{name:'application',items:Array.isArray(<developer.files>)?<developer.files>:[],allowed:applicationApproved},{name:'tests',items:Array.isArray(<testdeveloper.files>)?<testdeveloper.files>:[],allowed:testsApproved},{name:'documentation',items:Array.isArray(<documentationwriter.files>)?<documentationwriter.files>:[],allowed:docsApproved}];const errors=[];const seen=new Set();const files=[];let total=0;const safe=/^(?!\/)(?!.*\.\.)(?!.*\\)[A-Za-z0-9._/-]+$/;
for(const group of groups)for(const item of group.items){const path=String(item?.path??'').trim();const content=String(item?.content??'');const lower=path.toLowerCase();const emptyAllowed=lower==='__init__.py'||lower.endsWith('/__init__.py');if(!safe.test(path)||/^(\.git|\.gitea|\.github|ci|k8s|secrets)\//i.test(path)||/^\.env/i.test(path))errors.push(`Недопустимый path: ${path}`);if(!group.allowed.has(path))errors.push(`${group.name} generator returned a path outside its approved scope: ${path}`);if(!approved.has(path))errors.push(`Path отсутствует в architecture plan: ${path}`);if(seen.has(lower))errors.push(`Дубликат path: ${path}`);if(!content&&!emptyAllowed)errors.push(`Пустой файл: ${path}`);if(content.length>30000)errors.push(`Файл больше 30000 символов: ${path}`);if(group.name==='documentation'&&content.length<700)errors.push(`Документ слишком короткий: ${path}`);if(group.name==='documentation'&&(content.match(/^#{1,3}\s+.+$/gm)||[]).length<3)errors.push(`В документе недостаточно разделов: ${path}`);if(/\bTODO\b|заполнить позднее|coming soon/i.test(content))errors.push(`Обнаружена заглушка: ${path}`);if(/-----BEGIN .*PRIVATE KEY-----|(?:password|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}/i.test(content))errors.push(`Возможный секрет: ${path}`);seen.add(lower);total+=content.length;files.push({path,content,encoded_path:path.split('/').map(encodeURIComponent).join('/')});}
for(const path of approved)if(!seen.has(path.toLowerCase()))errors.push(`Не сгенерирован approved файл: ${path}`);
if(total>140000)errors.push('Общий объём проекта превышает 140000 символов');
return {valid:errors.length===0,errors,files,total_chars:total,summary:String(<developer.summary>??'')};
""",
    )
    blocks.append(inspect_files)
    repair = clone("03", "Developer", "Generation Repair")
    set_agent(
        repair,
        system="""
Ты выполняешь один ограниченный repair-проход по уже сгенерированному FastAPI-
проекту. Верни только JSON Response Format. Если ERRORS пуст, верни пустой
массив files и ничего не изменяй. Если ошибки есть, верни только отсутствующие
или исправленные файлы из APPROVED PLAN; полное содержимое файла заменит
первичный вариант. Не изменяй корректные файлы, не добавляй новые пути, не пиши
.gitea/**, ci/**, .env и секреты. Пустой __init__.py допустим. Документы должны
быть на русском, содержать минимум три содержательных Markdown-раздела и
соответствовать требованиям. Код и pytest-тесты должны быть завершёнными, без
TODO и заглушек. Не заявляй, что тесты уже выполнены.
""",
        user="""
REQUIREMENTS: <validateimplementationinput.result.artifact.requirements>
ARCHITECTURE: <validateimplementationinput.result.artifact.architecture>
TEST STRATEGY: <validateimplementationinput.result.artifact.test_strategy>
APPROVED PLAN: <validateimplementationinput.result.artifact.repository_plan.files>
ERRORS: <inspectgeneratedfiles.result.errors>
CURRENT GENERATED FILES: <inspectgeneratedfiles.result.files>

Исправь только перечисленные ошибки. Для отсутствующего approved файла создай
его, для некорректного — верни исправленное полное содержимое.
""",
        schema=FILES_SCHEMA,
        max_tokens=12288,
    )
    blocks.append(repair)
    merge_repair = clone("03", "Prepare Writes", "Merge Generation Repair")
    set_function(
        merge_repair,
        r"""
const plan=Array.isArray(<validateimplementationinput.result.artifact.repository_plan.files>)?<validateimplementationinput.result.artifact.repository_plan.files>:[];const approved=new Set(plan.map(x=>String(x?.path??'').trim()));const current=Array.isArray(<inspectgeneratedfiles.result.files>)?<inspectgeneratedfiles.result.files>:[];const attempted=<inspectgeneratedfiles.result.valid>!==true;const returned=attempted&&Array.isArray(<generationrepair.files>)?<generationrepair.files>:[];const errors=[];const merged=new Map();
for(const item of current){const path=String(item?.path??'').trim();if(approved.has(path))merged.set(path,{path,content:String(item?.content??'')});}
const repaired=new Set();for(const item of returned){const path=String(item?.path??'').trim();if(!approved.has(path)){errors.push(`Repair вернул неразрешённый path: ${path}`);continue;}if(repaired.has(path))errors.push(`Repair вернул дубликат: ${path}`);repaired.add(path);merged.set(path,{path,content:String(item?.content??'')});}
return {files:[...merged.values()],repair_attempted:attempted,repaired_paths:[...repaired],merge_errors:errors,summary:String(<generationrepair.summary>??'')};
""",
    )
    blocks.append(merge_repair)
    validate_files = clone("03", "Validate Generated Files")
    set_function(
        validate_files,
        r"""
const generated=Array.isArray(<mergegenerationrepair.result.files>)?<mergegenerationrepair.result.files>:[];const plan=Array.isArray(<validateimplementationinput.result.artifact.repository_plan.files>)?<validateimplementationinput.result.artifact.repository_plan.files>:[];const approved=new Set(plan.map(x=>String(x?.path??'').trim()));const docsApproved=new Set(<splitimplementationplan.result.documentation_files>.map(x=>String(x?.path??'').trim()));const errors=Array.isArray(<mergegenerationrepair.result.merge_errors>)?[...<mergegenerationrepair.result.merge_errors>]:[];const seen=new Set();const files=[];let total=0;const safe=/^(?!\/)(?!.*\.\.)(?!.*\\)[A-Za-z0-9._/-]+$/;
for(const item of generated){const path=String(item?.path??'').trim();const content=String(item?.content??'');const lower=path.toLowerCase();const emptyAllowed=lower==='__init__.py'||lower.endsWith('/__init__.py');if(!safe.test(path)||/^(\.git|\.gitea|\.github|ci|k8s|secrets)\//i.test(path)||/^\.env/i.test(path))errors.push(`Недопустимый path: ${path}`);if(!approved.has(path))errors.push(`Path отсутствует в architecture plan: ${path}`);if(seen.has(lower))errors.push(`Дубликат path: ${path}`);if(!content&&!emptyAllowed)errors.push(`Пустой файл: ${path}`);if(content.length>30000)errors.push(`Файл больше 30000 символов: ${path}`);if(docsApproved.has(path)&&content.length<700)errors.push(`Документ слишком короткий: ${path}`);if(docsApproved.has(path)&&(content.match(/^#{1,3}\s+.+$/gm)||[]).length<3)errors.push(`В документе недостаточно разделов: ${path}`);if(/\bTODO\b|заполнить позднее|coming soon/i.test(content))errors.push(`Обнаружена заглушка: ${path}`);if(/-----BEGIN .*PRIVATE KEY-----|(?:password|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}/i.test(content))errors.push(`Возможный секрет: ${path}`);seen.add(lower);total+=content.length;files.push({path,content,encoded_path:path.split('/').map(encodeURIComponent).join('/')});}
for(const path of approved)if(!seen.has(path.toLowerCase()))errors.push(`Не сгенерирован approved файл: ${path}`);if(total>140000)errors.push('Общий объём проекта превышает 140000 символов');return {valid:errors.length===0,errors,files,total_chars:total,repair_attempted:<mergegenerationrepair.result.repair_attempted>,repaired_paths:<mergegenerationrepair.result.repaired_paths>,summary:String(<mergegenerationrepair.result.summary>??'')};
""",
    )
    blocks.append(validate_files)
    files_valid = clone("03", "Files Valid")
    handles[files_valid["name"]] = set_condition(files_valid, [("if", "<validategeneratedfiles.result.valid> === true"), ("else", "")])
    blocks.append(files_valid)
    invalid_files = clone("03", "Invalid Generated Files")
    set_response(invalid_files, "<validategeneratedfiles.result>", 422)
    blocks.append(invalid_files)
    dry = clone("03", "Dry Run")
    handles[dry["name"]] = set_condition(dry, [("if", "<validateimplementationinput.result.dry_run> === true"), ("else", "")])
    blocks.append(dry)
    dry_result = clone("03", "Dry Run Result")
    set_response(dry_result, "<validategeneratedfiles.result>", 200)
    blocks.append(dry_result)
    prepare = clone("03", "Prepare Writes")
    blocks.append(prepare)
    create_loop = clone("03", "Create Files")
    blocks.append(create_loop)
    create_file = clone("03", "Create File 1")
    blocks.append(create_file)
    update_loop = clone("03", "Update Files")
    blocks.append(update_loop)
    update_file = clone("03", "Update File")
    blocks.append(update_file)
    verify = clone("03", "Verify Implementation Writes")
    blocks.append(verify)
    writes_complete = clone("03", "Writes Complete")
    handles[writes_complete["name"]] = set_condition(writes_complete, [("if", "<verifyimplementationwrites.result.valid> === true"), ("else", "")])
    blocks.append(writes_complete)
    partial = clone("03", "Partial Write")
    set_response(partial, "<verifyimplementationwrites.result>", 500)
    blocks.append(partial)
    contract = clone("03", "Prepare Development Contract")
    set_function(
        contract,
        r"""
const input=<validateimplementationinput.result>;const artifact=input.artifact;const value={schema_version:'1.0',contract_type:'ai-demo-development-contract',workflow_id:'03-implementation-demo',run_id:input.run_id,owner:input.owner,repo:input.repo,base_branch:input.base_branch,branch:input.branch,requirements:artifact.requirements,architecture:artifact.architecture,repository_plan:artifact.repository_plan};return {package_owner:String(<start.artifact_owner>),package_name:'development-contracts',package_version:input.run_id,file_name:'development-contract.json',json:JSON.stringify(value),contract:value};
""",
    )
    blocks.append(contract)
    publish_contract = clone("03", "Publish Development Contract")
    set_api(
        publish_contract,
        method="PUT",
        url="{{GITEA_URL}}/api/packages/<preparedevelopmentcontract.result.package_owner>/generic/<preparedevelopmentcontract.result.package_name>/<preparedevelopmentcontract.result.package_version>/<preparedevelopmentcontract.result.file_name>",
        body="<preparedevelopmentcontract.result.json>",
    )
    blocks.append(publish_contract)
    check_contract = clone("03", "Check Contract Publication")
    set_function(check_contract, "const status=Number(<publishdevelopmentcontract.status>);if(![200,201,204,409].includes(status))throw new Error(`Development contract upload failed: HTTP ${status}`);return {valid:true,status,already_exists:status===409};")
    blocks.append(check_contract)
    find_pr = clone("03", "Find Existing PR")
    set_api(
        find_pr,
        method="GET",
        url="{{GITEA_URL}}/api/v1/repos/<validateimplementationinput.result.owner>/<validateimplementationinput.result.repo>/pulls",
        params=[("state", "open"), ("page", "1"), ("limit", "100")],
    )
    blocks.append(find_pr)
    resolve_pr = clone("03", "Select Pull Request", "Resolve Existing PR")
    set_function(
        resolve_pr,
        r"""
const status = Number(<findexistingpr.status>);
if (status !== 200) throw new Error(`List pull requests failed: HTTP ${status}`);
const list = Array.isArray(<findexistingpr.data>) ? <findexistingpr.data> : [];
const branch = String(<validateimplementationinput.result.branch> ?? '');
const baseBranch = String(<validateimplementationinput.result.base_branch> ?? '');
const matches = list.filter(pr =>
  String(pr?.state ?? '') === 'open' &&
  String(pr?.head?.ref ?? '') === branch &&
  String(pr?.base?.ref ?? '') === baseBranch
);
if (matches.length > 1) throw new Error(`Multiple open pull requests match ${branch} -> ${baseBranch}`);
const pr = matches[0] ?? null;
const number = Number(pr?.number ?? 0);
const result = pr ? {
  status: 'pr_ready',
  run_id: <validateimplementationinput.result.run_id>,
  branch,
  files: <validategeneratedfiles.result.files>.map(x => x.path),
  pr_number: number,
  pr_url: String(pr?.html_url ?? ''),
  existing_pr: true,
  manual_merge_required: true
} : null;
return {found: Boolean(pr && Number.isInteger(number) && number > 0), result, scanned: list.length, branch, base_branch: baseBranch};
""",
    )
    blocks.append(resolve_pr)
    existing_pr = clone("03", "Existing PR Found")
    handles[existing_pr["name"]] = set_condition(existing_pr, [("if", "<resolveexistingpr.result.found> === true"), ("else", "")])
    blocks.append(existing_pr)
    create_pr = clone("03", "Create PR")
    set_api(
        create_pr,
        method="POST",
        url="{{GITEA_URL}}/api/v1/repos/<validateimplementationinput.result.owner>/<validateimplementationinput.result.repo>/pulls",
        body=r'''{
  "base": "<validateimplementationinput.result.base_branch>",
  "head": "<validateimplementationinput.result.branch>",
  "title": "WIP: AI implementation <validateimplementationinput.result.run_id>",
  "body": "AI-generated change. Manual review and merge are required.\n\nRun ID: <validateimplementationinput.result.run_id>"
}''',
    )
    blocks.append(create_pr)
    existing_response = clone("03", "PR Created", "Existing PR Ready")
    set_response(existing_response, "<resolveexistingpr.result.result>", 200)
    blocks.append(existing_response)
    created_result = clone("03", "Build PR Created Response", "Build Created PR Result")
    set_function(
        created_result,
        r"""
const pr = <createpr.data>;
const number = Number(pr?.number ?? 0);
if (!Number.isInteger(number) || number < 1) throw new Error('Created PR response does not contain a valid number');
return {status:'pr_ready',run_id:<validateimplementationinput.result.run_id>,branch:<validateimplementationinput.result.branch>,files:<validategeneratedfiles.result.files>.map(x=>x.path),pr_number:number,pr_url:String(pr?.html_url??''),existing_pr:false,manual_merge_required:true};
""",
    )
    blocks.append(created_result)
    created_response = clone("03", "PR Created", "Created PR Ready")
    set_response(created_response, "<buildcreatedprresult.result>", 200)
    blocks.append(created_response)

    edges = [
        ("Start", "Get Architecture Artifact", None),
        ("Get Architecture Artifact", "Validate Implementation Input", None),
        ("Validate Implementation Input", "Input Valid", None),
        ("Input Valid", "Get Base Branch", "if"),
        ("Input Valid", "Invalid Implementation", "else"),
        ("Get Base Branch", "List Branches", None),
        ("List Branches", "Resolve Branch", None),
        ("Resolve Branch", "Branch Context Valid", None),
        ("Branch Context Valid", "Target Branch Exists", "if"),
        ("Branch Context Valid", "Branch Context Error", "else"),
        ("Target Branch Exists", "Get Working Branch", "if"),
        ("Target Branch Exists", "Create Branch", "else"),
        ("Create Branch", "Check Branch Creation", None),
        ("Check Branch Creation", "Get Working Branch", None),
        ("Get Working Branch", "Get Target Branch Tree", None),
        ("Get Target Branch Tree", "Split Implementation Plan", None),
        ("Split Implementation Plan", "Developer", None),
        ("Developer", "Test Developer", None),
        ("Test Developer", "Documentation Writer", None),
        ("Documentation Writer", "Inspect Generated Files", None),
        ("Inspect Generated Files", "Generation Repair", None),
        ("Generation Repair", "Merge Generation Repair", None),
        ("Merge Generation Repair", "Validate Generated Files", None),
        ("Validate Generated Files", "Files Valid", None),
        ("Files Valid", "Dry Run", "if"),
        ("Files Valid", "Invalid Generated Files", "else"),
        ("Dry Run", "Dry Run Result", "if"),
        ("Dry Run", "Prepare Writes", "else"),
        ("Prepare Writes", "Create Files", None),
        ("Create Files", "Update Files", "loop-end"),
        ("Update Files", "Verify Implementation Writes", "loop-end"),
        ("Verify Implementation Writes", "Writes Complete", None),
        ("Writes Complete", "Prepare Development Contract", "if"),
        ("Writes Complete", "Partial Write", "else"),
        ("Prepare Development Contract", "Publish Development Contract", None),
        ("Publish Development Contract", "Check Contract Publication", None),
        ("Check Contract Publication", "Find Existing PR", None),
        ("Find Existing PR", "Resolve Existing PR", None),
        ("Resolve Existing PR", "Existing PR Found", None),
        ("Existing PR Found", "Existing PR Ready", "if"),
        ("Existing PR Found", "Create PR", "else"),
        ("Create PR", "Build Created PR Result", None),
        ("Build Created PR Result", "Created PR Ready", None),
    ]
    return make_workflow(
        "03",
        blocks,
        edges,
        name="03 — Генерация FastAPI и PR [demo simple]",
        description="Application Developer, Test Developer и Documentation Writer создают свои части проекта без лимита числа файлов; один ограниченный repair-проход исправляет дефекты генерации до записи и PR.",
        condition_handles=handles,
        loops=[
            ("Create Files", "Create File 1", "<preparewrites.result.create_files>", 100),
            ("Update Files", "Update File", "<preparewrites.result.update_files>", 100),
        ],
    )


def build_workflow_04() -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    handles: dict[str, dict[str, str]] = {}
    start = clone("04", "Start")
    set_start(
        start,
        [
            {"name": "run_id", "description": "Исходный run_id"},
            {"name": "owner", "value": "labadmin"},
            {"name": "repo", "value": "demo-fastapi"},
            {"name": "branch"},
            {"name": "commit_sha"},
            {"name": "pr_number", "type": "number", "value": 0},
            {"name": "artifact_owner", "value": "labadmin"},
            {"name": "artifact_package", "value": "ci-artifacts"},
            {"name": "artifact_version"},
            {"name": "context_owner", "value": "labadmin"},
            {"name": "context_package", "value": "development-contracts"},
            {"name": "context_version"},
            {"name": "attempt", "type": "number", "value": 1},
            {"name": "dry_run", "type": "boolean", "value": False},
        ],
    )
    blocks.append(start)
    validate_input = clone("04", "Validate Input")
    set_function(
        validate_input,
        r"""
const text=v=>String(v??'').trim();const safe=v=>/^[A-Za-z0-9_.-]{1,100}$/.test(v);const errors=[];
const runId=text(<start.run_id>),owner=text(<start.owner>),repo=text(<start.repo>),branch=text(<start.branch>),commitSha=text(<start.commit_sha>).toLowerCase(),artifactOwner=text(<start.artifact_owner>),artifactPackage=text(<start.artifact_package>),artifactVersion=text(<start.artifact_version>),contextOwner=text(<start.context_owner>),contextPackage=text(<start.context_package>),contextVersion=text(<start.context_version>);const attempt=Number(<start.attempt>??1),prNumber=Number(<start.pr_number>??0);
if(!/^run-\d{8}-\d{6}-[a-z0-9]{6}$/.test(runId))errors.push('Некорректный run_id');if(!safe(owner)||!safe(repo))errors.push('Некорректный owner/repo');if(!branch||branch.length>200||branch.includes('..'))errors.push('Некорректная branch');if(!/^[0-9a-f]{40,64}$/.test(commitSha))errors.push('Некорректный commit_sha');for(const [name,value] of [['artifact_owner',artifactOwner],['artifact_package',artifactPackage],['artifact_version',artifactVersion],['context_owner',contextOwner],['context_package',contextPackage],['context_version',contextVersion]])if(!safe(value))errors.push(`Некорректный ${name}`);if(!Number.isInteger(prNumber)||prNumber<1)errors.push('Некорректный pr_number');if(!Number.isInteger(attempt)||attempt<1||attempt>5)errors.push('Demo поддерживает attempts 1..5');
return {valid:errors.length===0,errors,run_id:runId,owner,repo,branch,branch_encoded:encodeURIComponent(branch),commit_sha:commitSha,pr_number:prNumber,artifact_owner:artifactOwner,artifact_package:artifactPackage,artifact_version:artifactVersion,artifact_version_encoded:encodeURIComponent(artifactVersion),context_owner:contextOwner,context_package:contextPackage,context_version:contextVersion,context_version_encoded:encodeURIComponent(contextVersion),attempt,dry_run:Boolean(<start.dry_run>)};
""",
    )
    blocks.append(validate_input)
    input_valid = clone("04", "Input Valid")
    handles[input_valid["name"]] = set_condition(input_valid, [("if", "<validateinput.result.valid> === true"), ("else", "")])
    blocks.append(input_valid)
    invalid_input = clone("04", "Invalid Input 422", "Invalid Input")
    set_response(invalid_input, "<validateinput.result>", 422)
    blocks.append(invalid_input)
    get_summary = clone("04", "Get CI Summary")
    set_api(get_summary, method="GET", url="{{GITEA_URL}}/api/packages/<validateinput.result.artifact_owner>/generic/<validateinput.result.artifact_package>/<validateinput.result.artifact_version_encoded>/ci-summary.json")
    blocks.append(get_summary)
    get_findings = clone("04", "Get Findings")
    set_api(get_findings, method="GET", url="{{GITEA_URL}}/api/packages/<validateinput.result.artifact_owner>/generic/<validateinput.result.artifact_package>/<validateinput.result.artifact_version_encoded>/findings.json")
    blocks.append(get_findings)
    get_pytest_log = clone("04", "Get Findings", "Get Pytest Log")
    set_api(get_pytest_log, method="GET", url="{{GITEA_URL}}/api/packages/<validateinput.result.artifact_owner>/generic/<validateinput.result.artifact_package>/<validateinput.result.artifact_version_encoded>/pytest.log")
    blocks.append(get_pytest_log)
    get_contract = clone("04", "Get Development Contract")
    set_api(get_contract, method="GET", url="{{GITEA_URL}}/api/packages/<validateinput.result.context_owner>/generic/<validateinput.result.context_package>/<validateinput.result.context_version_encoded>/development-contract.json")
    blocks.append(get_contract)
    build_context = clone("04", "Build Artifact Context", "Build CI Context")
    set_function(
        build_context,
        r"""
function parse(v){if(v&&typeof v==='object')return v;if(typeof v!=='string')return null;try{return JSON.parse(v);}catch(_){return null;}}
const errors=[];let summary=parse(<getcisummary.data>),findings=parse(<getfindings.data>),contract=parse(<getdevelopmentcontract.data>);const rawPytest=<getpytestlog.data>;const pytestLog=typeof rawPytest==='string'?rawPytest:String(rawPytest??'');if(summary?.data&&typeof summary.data==='object')summary=summary.data;if(contract?.data&&typeof contract.data==='object')contract=contract.data;
if(Number(<getcisummary.status>)!==200||!summary)errors.push('ci-summary.json не получен');if(Number(<getfindings.status>)!==200||!Array.isArray(findings))errors.push('findings.json не получен');if(Number(<getpytestlog.status>)!==200||!pytestLog.trim())errors.push('pytest.log не получен');if(Number(<getdevelopmentcontract.status>)!==200||!contract)errors.push('development-contract.json не получен');if(contract&&(String(contract.owner)!==String(<validateinput.result.owner>)||String(contract.repo)!==String(<validateinput.result.repo>)))errors.push('Development contract относится к другому repository');
const approved=Array.isArray(contract?.repository_plan?.files)?contract.repository_plan.files.map(x=>String(typeof x==='string'?x:x?.path??'')).filter(Boolean):[];if(!approved.length)errors.push('Нет approved repository paths');
const pytestStage=Array.isArray(summary?.stages)?summary.stages.find(x=>String(x?.name??'').toLowerCase()==='pytest'):null;const noTestsCollected=Number(pytestStage?.exit_code)===5||/\bno tests ran\b|collected\s+0\s+items?/i.test(pytestLog);const diagnosticText=`${JSON.stringify(summary??{})}\n${JSON.stringify(findings??[])}\n${pytestLog}`;const transientFailure=!noTestsCollected&&/(connection (?:reset|refused)|timed?\s*out|temporary failure|service unavailable|runner unavailable|network is unreachable|i\/o timeout|tls handshake timeout|http\s+5\d\d)/i.test(diagnosticText);
return {valid:errors.length===0,errors,summary,findings:Array.isArray(findings)?findings:[],pytest_log:pytestLog.slice(-20000),contract,approved_paths:[...new Set(approved)],passed:summary?.quality_gate?.passed===true,no_tests_collected:noTestsCollected,transient_failure:transientFailure};
""",
    )
    blocks.append(build_context)
    context_valid = clone("04", "Artifacts Valid", "CI Context Valid")
    handles[context_valid["name"]] = set_condition(context_valid, [("if", "<buildcicontext.result.valid> === true"), ("else", "")])
    blocks.append(context_valid)
    invalid_context = clone("04", "Invalid Artifacts 424", "Invalid CI Context")
    set_response(invalid_context, "<buildcicontext.result>", 424)
    blocks.append(invalid_context)
    passed = clone("04", "Decision Route", "CI Passed")
    handles[passed["name"]] = set_condition(passed, [("if", "<buildcicontext.result.passed> === true"), ("else", "")])
    blocks.append(passed)
    passed_response = clone("04", "CI Passed", "CI Success")
    set_response(passed_response, "<buildcicontext.result>", 200)
    blocks.append(passed_response)
    analyst = clone("04", "CI Result Analyst")
    set_agent(
        analyst,
        system="""
Ты анализируешь упавший CI демонстрационного FastAPI-проекта. Верни только JSON
Response Format. Выбери repair только для локальной ошибки в application-owned
коде, тестах, зависимостях или документации. Для ошибки runner, Docker, Gitea,
секретов, сети, .gitea/** или ci/** выбери manual. Если pytest.log точно указывает на локальный
дефект в approved application-owned файле, выбери repair. `no tests ran`,
`collected 0 items` и pytest exit code 5 всегда означают repair тестовых файлов,
а не CI-инфраструктуры: выбери repair и укажи approved `tests/test_*.py`.
Укажи не более пяти файлов.
""",
        user="""
CI SUMMARY: <buildcicontext.result.summary>
FINDINGS: <buildcicontext.result.findings>
PYTEST LOG: <buildcicontext.result.pytest_log>
NO TESTS COLLECTED: <buildcicontext.result.no_tests_collected>
TRANSIENT FAILURE: <buildcicontext.result.transient_failure>
APPROVED PATHS: <buildcicontext.result.approved_paths>
ATTEMPT: <validateinput.result.attempt> из 5
""",
        schema=CI_ANALYSIS_SCHEMA,
        max_tokens=4096,
    )
    blocks.append(analyst)
    route = clone("04", "Decision Route", "Repair Allowed")
    handles[route["name"]] = set_condition(
        route,
        [
            ("if", "(String(<ciresultanalyst.decision> ?? '') === 'repair' || <buildcicontext.result.no_tests_collected> === true) && Number(<validateinput.result.attempt>) <= 5"),
            ("else if", "<buildcicontext.result.transient_failure> === true && Number(<validateinput.result.attempt>) < 5"),
            ("else", ""),
        ],
    )
    blocks.append(route)
    retry_ci = clone("04", "Trigger Recheck CI", "Retry CI Without Changes")
    set_api(
        retry_ci,
        method="POST",
        url="{{GITEA_URL}}/api/v1/repos/<validateinput.result.owner>/<validateinput.result.repo>/actions/workflows/pipeline.yml/dispatches",
        body="{\"ref\":\"<validateinput.result.branch>\",\"inputs\":{\"pr_number\":\"<validateinput.result.pr_number>\",\"context_version\":\"<validateinput.result.context_version>\",\"repair_attempt\":\"<validateinput.result.attempt>\",\"run_id\":\"<validateinput.result.run_id>\"}}",
        params=[("return_run_details", "true")],
    )
    blocks.append(retry_ci)
    check_retry = clone("04", "Check Recheck CI Dispatch", "Check Autonomous Retry")
    retry_check_code = str(check_retry["subBlocks"]["code"]["value"])
    retry_check_code = retry_check_code.replace("<triggerrecheckci.", "<retryciwithoutchanges.")
    set_function(check_retry, retry_check_code)
    blocks.append(check_retry)
    retry_scheduled = clone("04", "Revision Written", "Autonomous Retry Scheduled")
    set_response(retry_scheduled, "<checkautonomousretry.result>", 200)
    blocks.append(retry_scheduled)
    terminal = clone("04", "Needs Human", "Autonomous Limit Reached")
    set_response(terminal, "<ciresultanalyst>", 200)
    blocks.append(terminal)
    get_branch = clone("04", "Get Branch")
    blocks.append(get_branch)
    check_head = clone("04", "Check Branch Head")
    set_function(
        check_head,
        r"""
const status=Number(<getbranch.status>),actual=String(<getbranch.data.commit.id>??'').toLowerCase(),expected=String(<validateinput.result.commit_sha>??'').toLowerCase();return {valid:status===200&&actual===expected,status,actual,expected};
""",
    )
    blocks.append(check_head)
    fresh = clone("04", "Branch Fresh")
    handles[fresh["name"]] = set_condition(fresh, [("if", "<checkbranchhead.result.valid> === true"), ("else", "")])
    blocks.append(fresh)
    stale = clone("04", "Stale Branch 409", "Stale Branch")
    set_response(stale, "<checkbranchhead.result>", 409)
    blocks.append(stale)
    select_paths = clone("04", "Select Revision Paths")
    set_function(
        select_paths,
        r"""
const approved=Array.isArray(<buildcicontext.result.approved_paths>)?<buildcicontext.result.approved_paths>:[];const approvedSet=new Set(approved);const requested=Array.isArray(<ciresultanalyst.files>)?<ciresultanalyst.files>:[];const paths=[];const seen=new Set();const protectedPath=p=>/^(\.git|\.gitea|\.github|ci|k8s|secrets)\//i.test(p)||/^\.env/i.test(p);const relevant=p=>/\.py$/i.test(p)||/^requirements.*\.txt$/i.test(p);
function add(raw){if(paths.length>=10)return;const path=String(raw??'').trim().replace(/^\.\//,'');if(approvedSet.has(path)&&!protectedPath(path)&&!seen.has(path)){seen.add(path);paths.push({path,encoded_path:path.split('/').map(encodeURIComponent).join('/')});}}
const noTestsCollected=<buildcicontext.result.no_tests_collected>===true;const testPath=p=>/^tests\/(?:test_.*|.*_test)\.py$/i.test(String(p??''));
if(noTestsCollected){for(const path of approved){if(testPath(path))add(path);}}for(const raw of requested)add(raw);for(const path of approved){if(relevant(path))add(path);}
const hasTestPath=paths.some(x=>testPath(x.path));const errors=[];if(!paths.length)errors.push('Не выбраны безопасные файлы');if(noTestsCollected&&!hasTestPath)errors.push('В approved plan нет доступного pytest-модуля tests/test_*.py');
return {valid:errors.length===0&&paths.length<=10,errors,paths:paths.slice(0,10),no_tests_collected:noTestsCollected};
""",
    )
    blocks.append(select_paths)
    scope_valid = clone("04", "Revision Scope Valid")
    handles[scope_valid["name"]] = set_condition(scope_valid, [("if", "<selectrevisionpaths.result.valid> === true"), ("else", "")])
    blocks.append(scope_valid)
    scope_error = clone("04", "Revision Scope Needs Human", "Scope Needs Human")
    set_response(scope_error, "<selectrevisionpaths.result>", 200)
    blocks.append(scope_error)
    read_loop = clone("04", "Read Revision Files")
    blocks.append(read_loop)
    read_file = clone("04", "Read Revision File")
    set_api(
        read_file,
        method="GET",
        url="{{GITEA_URL}}/api/v1/repos/<validateinput.result.owner>/<validateinput.result.repo>/contents/<readrevisionfiles.currentItem.encoded_path>?ref=<validateinput.result.branch_encoded>",
    )
    blocks.append(read_file)
    revision_context = clone("04", "Build Revision Context")
    revision_context_code = str(revision_context["subBlocks"]["code"]["value"])
    revision_context_code = revision_context_code.replace("totalChars > 30000", "totalChars > 60000")
    revision_context_code = revision_context_code.replace("превышает 30000", "превышает 60000")
    set_function(revision_context, revision_context_code)
    blocks.append(revision_context)
    repo_context_valid = clone("04", "Revision Context Valid")
    handles[repo_context_valid["name"]] = set_condition(repo_context_valid, [("if", "<buildrevisioncontext.result.valid> === true"), ("else", "")])
    blocks.append(repo_context_valid)
    repo_context_error = clone("04", "Revision Context Error 424", "Repository Context Error")
    set_response(repo_context_error, "<buildrevisioncontext.result>", 424)
    blocks.append(repo_context_error)
    revision = clone("04", "Revision Developer")
    set_agent(
        revision,
        system="""
Ты исправляешь один упавший CI демонстрационного FastAPI-проекта. Верни только
JSON Response Format. Меняй только переданные файлы, возвращай их полное новое
содержимое. Исправь указанную причину CI, сохрани утверждённое поведение, не
добавляй секреты, TODO и изменения platform-owned файлов. Ищи корневую причину во всех переданных связанных
файлах. Не создавай параллельное состояние или singleton, если приложение фактически использует другой экземпляр.
Предпочитай исправление application-кода; меняй тест только если он явно противоречит requirements.
Никогда не заменяй тестовый модуль только fixtures, imports или helper-функциями.
Сохраняй все существующие функции `def test_*`, если они не противоречат требованиям.
Если NO TESTS COLLECTED=true, верни минимум один approved `tests/test_*.py` с
обнаруживаемыми pytest функциями `def test_*`; исправь helper-код, не удаляя тестовые сценарии.
""",
        user="""
CI SUMMARY: <buildcicontext.result.summary>
FINDINGS: <buildcicontext.result.findings>
PYTEST LOG: <buildcicontext.result.pytest_log>
NO TESTS COLLECTED: <buildcicontext.result.no_tests_collected>
INSTRUCTIONS: <ciresultanalyst.instructions>
REQUIREMENTS: <buildcicontext.result.contract.requirements>
REPOSITORY PLAN: <buildcicontext.result.contract.repository_plan>
CURRENT FILES: <buildrevisioncontext.result.files>
""",
        schema=REVISION_SCHEMA,
        max_tokens=8192,
    )
    blocks.append(revision)
    validate_revision = clone("04", "Validate Draft Revision", "Validate Revision")
    set_function(
        validate_revision,
        r"""
const returned=Array.isArray(<revisiondeveloper.files>)?<revisiondeveloper.files>:[];const current=Array.isArray(<buildrevisioncontext.result.files>)?<buildrevisioncontext.result.files>:[];const allowed=new Map(current.map(x=>[String(x.path),x]));const errors=[];const files=[];const seen=new Set();let total=0;const noTestsCollected=<buildcicontext.result.no_tests_collected>===true;const testPath=p=>/^tests\/(?:test_.*|.*_test)\.py$/i.test(String(p??''));const countTests=text=>(String(text??'').match(/(?:^|\n)\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]*\s*\(/g)||[]).length;let returnedTestModule=false;
for(const item of returned){const path=String(item?.path??'').trim().replace(/^\.\//,'');const content=String(item?.content??'');if(seen.has(path))errors.push(`Дубликат: ${path}`);if(!allowed.has(path))errors.push(`Файл не разрешён: ${path}`);if(/^(\.git|\.gitea|\.github|ci|k8s|secrets)\//i.test(path)||/^\.env/i.test(path))errors.push(`Защищённый path: ${path}`);if(!content)errors.push(`Пустой content: ${path}`);if(content.length>20000)errors.push(`Файл слишком большой: ${path}`);if(allowed.has(path)&&content===allowed.get(path).content)errors.push(`Файл не изменён: ${path}`);if(/-----BEGIN .*PRIVATE KEY-----|(?:password|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}/i.test(content))errors.push(`Возможный секрет: ${path}`);if(testPath(path)){returnedTestModule=true;const oldCount=countTests(allowed.get(path)?.content);const newCount=countTests(content);if(newCount<1)errors.push(`Pytest не обнаружит тесты в ${path}: нужны функции def test_*`);if(oldCount>0&&newCount<oldCount)errors.push(`Исправление удаляет тестовые функции из ${path}: было ${oldCount}, стало ${newCount}`);}seen.add(path);total+=content.length;files.push({path,content,sha:String(allowed.get(path)?.sha??''),encoded_path:path.split('/').map(encodeURIComponent).join('/')});}
if(noTestsCollected&&!returnedTestModule)errors.push('При pytest exit code 5 нужно вернуть исправленный tests/test_*.py');if(files.length<1||files.length>5)errors.push('Нужно 1–5 исправленных файлов');if(total>40000)errors.push('Исправления превышают 40000 символов');return {valid:errors.length===0,errors,files,summary:String(<revisiondeveloper.summary>??''),no_tests_collected:noTestsCollected};
""",
    )
    blocks.append(validate_revision)
    revision_safeguard = clone("04", "Revision Reviewer", "Revision Safeguard")
    set_agent(
        revision_safeguard,
        system="""
Ты выполняешь обязательный контрольный проход исправления упавшего CI FastAPI-проекта.
Верни только JSON Response Format с полным содержимым изменяемых файлов.
Опирайся на CURRENT FILES и требования. Если DRAFT VALID=false, устрани каждую
ошибку DRAFT ERRORS. Если черновик уже допустим, сохрани его полезные изменения.
Не выходи за пути из CURRENT FILES и не изменяй platform-owned файлы.
Никогда не заменяй тестовый модуль только imports, fixtures или helper-функциями.
Сохрани все существующие `def test_*`, если они не противоречат требованиям.
При NO TESTS COLLECTED=true финальный `tests/test_*.py` обязан содержать
обнаруживаемые pytest-функции `def test_*`. Не заявляй, что CI уже прошёл.
""",
        user="""
CI SUMMARY: <buildcicontext.result.summary>
PYTEST LOG: <buildcicontext.result.pytest_log>
NO TESTS COLLECTED: <buildcicontext.result.no_tests_collected>
REQUIREMENTS: <buildcicontext.result.contract.requirements>
CURRENT FILES: <buildrevisioncontext.result.files>
DRAFT FILES: <revisiondeveloper.files>
DRAFT VALID: <validaterevision.result.valid>
DRAFT ERRORS: <validaterevision.result.errors>
""",
        schema=REVISION_SCHEMA,
        max_tokens=8192,
    )
    blocks.append(revision_safeguard)
    validate_final_revision = clone("04", "Validate Final Revision")
    final_validation_code = str(validate_revision["subBlocks"]["code"]["value"])
    final_validation_code = final_validation_code.replace("<revisiondeveloper.files>", "<revisionsafeguard.files>")
    final_validation_code = final_validation_code.replace("<revisiondeveloper.summary>", "<revisionsafeguard.summary>")
    set_function(validate_final_revision, final_validation_code)
    blocks.append(validate_final_revision)
    revision_valid = clone("04", "Revision Valid")
    handles[revision_valid["name"]] = set_condition(revision_valid, [("if", "<validatefinalrevision.result.valid> === true"), ("else", "")])
    blocks.append(revision_valid)
    revision_invalid = clone("04", "Revision Needs Human", "Invalid Revision")
    set_response(revision_invalid, "<validaterevision.result>", 200)
    blocks.append(revision_invalid)
    prepare = clone("04", "Prepare Revision")
    prepare_code = str(prepare["subBlocks"]["code"]["value"])
    prepare_code = prepare_code.replace("<normalizedecision.result.protected_findings>", "[]")
    prepare_code = prepare_code.replace("next_attempt: Number(<validateinput.result.attempt>) + 1", "next_attempt: Number(<validateinput.result.attempt>)")
    set_function(prepare, prepare_code)
    blocks.append(prepare)
    dry = clone("04", "Dry Run")
    handles[dry["name"]] = set_condition(dry, [("if", "<validateinput.result.dry_run> === true"), ("else", "")])
    blocks.append(dry)
    dry_result = clone("04", "Dry Run Result")
    set_response(dry_result, "<validatefinalrevision.result>", 200)
    blocks.append(dry_result)
    write_loop = clone("04", "Write Revision Files")
    blocks.append(write_loop)
    update_file = clone("04", "Update Revision File")
    blocks.append(update_file)
    verify = clone("04", "Verify Revision Writes")
    verify_code = str(verify["subBlocks"]["code"]["value"]).replace("<normalizedecision.result.protected_findings>", "[]")
    verify_code = verify_code.replace("next_attempt: Number(<validateinput.result.attempt>) + 1", "next_attempt: Number(<validateinput.result.attempt>)")
    set_function(verify, verify_code)
    blocks.append(verify)
    writes_complete = clone("04", "Writes Complete")
    handles[writes_complete["name"]] = set_condition(writes_complete, [("if", "<verifyrevisionwrites.result.valid> === true"), ("else", "")])
    blocks.append(writes_complete)
    partial = clone("04", "Partial Write 500", "Partial Write")
    set_response(partial, "<verifyrevisionwrites.result>", 500)
    blocks.append(partial)
    trigger = clone("04", "Trigger Recheck CI")
    set_api(
        trigger,
        method="POST",
        url="{{GITEA_URL}}/api/v1/repos/<validateinput.result.owner>/<validateinput.result.repo>/actions/workflows/pipeline.yml/dispatches",
        body="{\"ref\":\"<validateinput.result.branch>\",\"inputs\":{\"pr_number\":\"<validateinput.result.pr_number>\",\"context_version\":\"<validateinput.result.context_version>\",\"repair_attempt\":\"<preparerevision.result.next_attempt>\",\"run_id\":\"<validateinput.result.run_id>\"}}",
        params=[("return_run_details", "true")],
    )
    blocks.append(trigger)
    check_dispatch = clone("04", "Check Recheck CI Dispatch")
    blocks.append(check_dispatch)
    completed = clone("04", "Revision Written", "Repair Completed")
    set_response(completed, "<verifyrevisionwrites.result>", 200)
    blocks.append(completed)

    edges = [
        ("Start", "Validate Input", None),
        ("Validate Input", "Input Valid", None),
        ("Input Valid", "Get CI Summary", "if"),
        ("Input Valid", "Invalid Input", "else"),
        ("Get CI Summary", "Get Findings", None),
        ("Get Findings", "Get Pytest Log", None),
        ("Get Pytest Log", "Get Development Contract", None),
        ("Get Development Contract", "Build CI Context", None),
        ("Build CI Context", "CI Context Valid", None),
        ("CI Context Valid", "CI Passed", "if"),
        ("CI Context Valid", "Invalid CI Context", "else"),
        ("CI Passed", "CI Success", "if"),
        ("CI Passed", "CI Result Analyst", "else"),
        ("CI Result Analyst", "Repair Allowed", None),
        ("Repair Allowed", "Get Branch", "if"),
        ("Repair Allowed", "Retry CI Without Changes", "else if"),
        ("Repair Allowed", "Autonomous Limit Reached", "else"),
        ("Retry CI Without Changes", "Check Autonomous Retry", None),
        ("Check Autonomous Retry", "Autonomous Retry Scheduled", None),
        ("Get Branch", "Check Branch Head", None),
        ("Check Branch Head", "Branch Fresh", None),
        ("Branch Fresh", "Select Revision Paths", "if"),
        ("Branch Fresh", "Stale Branch", "else"),
        ("Select Revision Paths", "Revision Scope Valid", None),
        ("Revision Scope Valid", "Read Revision Files", "if"),
        ("Revision Scope Valid", "Scope Needs Human", "else"),
        ("Read Revision Files", "Build Revision Context", "loop-end"),
        ("Build Revision Context", "Revision Context Valid", None),
        ("Revision Context Valid", "Revision Developer", "if"),
        ("Revision Context Valid", "Repository Context Error", "else"),
        ("Revision Developer", "Validate Revision", None),
        ("Validate Revision", "Revision Safeguard", None),
        ("Revision Safeguard", "Validate Final Revision", None),
        ("Validate Final Revision", "Revision Valid", None),
        ("Revision Valid", "Prepare Revision", "if"),
        ("Revision Valid", "Invalid Revision", "else"),
        ("Prepare Revision", "Dry Run", None),
        ("Dry Run", "Dry Run Result", "if"),
        ("Dry Run", "Write Revision Files", "else"),
        ("Write Revision Files", "Verify Revision Writes", "loop-end"),
        ("Verify Revision Writes", "Writes Complete", None),
        ("Writes Complete", "Trigger Recheck CI", "if"),
        ("Writes Complete", "Partial Write", "else"),
        ("Trigger Recheck CI", "Check Recheck CI Dispatch", None),
        ("Check Recheck CI Dispatch", "Repair Completed", None),
    ]
    return make_workflow(
        "04",
        blocks,
        edges,
        name="04 — CI-анализ и автоисправление [demo simple]",
        description="CI-анализ, контекст репозитория и до пяти последовательных repair-попыток; pytest exit code 5 принудительно исправляет тесты, а retry без изменений разрешён только для временного инфраструктурного сбоя.",
        condition_handles=handles,
        loops=[
            ("Read Revision Files", "Read Revision File", "<selectrevisionpaths.result.paths>", 10),
            ("Write Revision Files", "Update Revision File", "<preparerevision.result.update_files>", 5),
        ],
    )


def main() -> None:
    WORKFLOWS.mkdir(parents=True, exist_ok=True)
    generated = {
        "01": build_workflow_01(),
        "02": build_workflow_02(),
        "03": build_workflow_03(),
        "04": build_workflow_04(),
    }
    for prefix, workflow in generated.items():
        (WORKFLOWS / OUTPUT_FILES[prefix]).write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    manifest = {
        "schema_version": "1.0",
        "bundle": "fastapi-demo-simple-v1",
        "bundle_revision": "1.9.1",
        "sim_graph_fixes": [
            "condition source handles use the condition- prefix",
            "loop children use the regenerated parentId and parent extent",
            "mutually exclusive PR branches do not read skipped block outputs",
            "open pull requests are matched locally by exact head and base refs",
            "Workflow 04 accepts and executes repair attempts 1 through 5",
            "Workflow 04 reads pytest.log before deciding between repair and manual handling",
            "repair attempts advance once per failed CI cycle without skipping even numbers",
            "Workflow 04 reads related approved Python files and retries ambiguous failures autonomously",
            "Workflow 04 treats pytest exit code 5 and no-tests-collected as a deterministic test repair",
            "Workflow 04 retries the same commit only for identified transient infrastructure failures",
            "Workflow 04 rejects revisions that remove existing pytest test functions",
            "Workflow 04 runs a mandatory safeguard model pass with deterministic draft validation feedback",
            "Gitea run names and logs expose the AI repair counter separately from the Actions run-attempt counter",
            "Workflow 01 records three mandatory documentation deliverables",
            "Workflow 02 requires every documentation file in the approved repository plan",
            "Workflow 02 and Workflow 03 do not impose a semantic file-count limit",
            "Workflow 03 delegates application code, tests, and documentation to separate bounded model calls",
            "Workflow 03 rejects incomplete or placeholder documentation",
            "Workflow 03 permits empty Python __init__.py package markers",
            "Workflow 03 performs one bounded pre-write generation repair pass",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model": MODEL,
        "thinking": "none",
        "target_repository": "labadmin/demo-fastapi",
        "workflows": [f"workflows/{OUTPUT_FILES[key]}" for key in generated],
        "block_counts": {
            key: len(workflow["state"]["blocks"])
            for key, workflow in generated.items()
        },
        "automatic_ci_repairs": 5,
        "required_project_documentation": REQUIRED_DOCUMENTATION_PATHS,
        "required_sim_environment": [
            "GITEA_URL",
            "GITEA_TOKEN",
            "SIM_INTERNAL_URL",
            "SIM_WORKFLOW02_ID",
            "SIM_WORKFLOW03_ID",
            "SIM_WORKFLOW_API_KEY",
        ],
        "gitea_platform": "../../platform",
        "manual_merge_required": True,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({"generated": [OUTPUT_FILES[key] for key in generated]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
