from __future__ import annotations

import json
import base64
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
WORKFLOWS = ROOT / "workflows"
FILES = sorted(WORKFLOWS.glob("*.json"))
PLACEHOLDER = re.compile(r"<([a-z0-9]+)(?:\.[A-Za-z0-9_]+)+>", re.IGNORECASE)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def blocks(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return list(workflow["state"]["blocks"].values())


def named(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [item for item in blocks(workflow) if item["name"] == name]
    if len(matches) != 1:
        raise AssertionError(f"{name}: expected one block, got {len(matches)}")
    return matches[0]


class DemoWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node.js is required")
        cls.workflows = {path.name: load(path) for path in FILES}

    def compile_js(self, code: str) -> None:
        normalized = PLACEHOLDER.sub("null", code)
        runner = "new Function(process.argv[1]);"
        result = subprocess.run(
            [self.node, "-e", runner, normalized],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr + "\n" + normalized)

    def execute_js(self, code: str, replacements: dict[str, Any]) -> Any:
        normalized = code
        for placeholder, value in replacements.items():
            normalized = normalized.replace(
                placeholder,
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            )
        unresolved = PLACEHOLDER.findall(normalized)
        self.assertEqual([], unresolved, normalized)
        runner = """
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = new Function(input.code)();
process.stdout.write(JSON.stringify(result));
"""
        result = subprocess.run(
            [self.node, "-e", runner],
            input=json.dumps({"code": normalized}, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr + "\n" + normalized)
        return json.loads(result.stdout)

    def test_four_importable_workflows_exist(self) -> None:
        self.assertEqual(4, len(self.workflows))
        self.assertEqual(
            {"01", "02", "03", "04"},
            {name[:2] for name in self.workflows},
        )

    def test_graphs_are_reachable_and_references_resolve(self) -> None:
        for name, workflow in self.workflows.items():
            values = blocks(workflow)
            by_id = {item["id"]: item for item in values}
            by_slug = {slug(item["name"]): item for item in values}
            self.assertEqual(len(values), len(by_id), name)
            starts = [item for item in values if item["type"] == "start_trigger"]
            self.assertEqual(1, len(starts), name)
            adjacency: dict[str, set[str]] = {item["id"]: set() for item in values}
            for edge in workflow["state"]["edges"]:
                self.assertIn(edge["source"], by_id, name)
                self.assertIn(edge["target"], by_id, name)
                adjacency[edge["source"]].add(edge["target"])
            reached: set[str] = set()
            pending = [starts[0]["id"]]
            while pending:
                current = pending.pop()
                if current in reached:
                    continue
                reached.add(current)
                pending.extend(adjacency[current] - reached)
            self.assertEqual(set(by_id), reached, f"{name}: unreachable blocks")
            raw = json.dumps(workflow, ensure_ascii=False)
            missing = sorted({match.group(1).lower() for match in PLACEHOLDER.finditer(raw)} - set(by_slug))
            self.assertEqual([], missing, f"{name}: missing refs")

    def test_sim_handles_loop_nesting_and_branch_dependencies(self) -> None:
        for name, workflow in self.workflows.items():
            values = blocks(workflow)
            by_id = {item["id"]: item for item in values}
            by_slug = {slug(item["name"]): item for item in values}
            edges = workflow["state"]["edges"]
            incoming: dict[str, list[dict[str, Any]]] = {item["id"]: [] for item in values}
            outgoing: dict[str, list[dict[str, Any]]] = {item["id"]: [] for item in values}
            for edge in edges:
                incoming[edge["target"]].append(edge)
                outgoing[edge["source"]].append(edge)
                self.assertEqual("target", edge.get("targetHandle"), f"{name}: invalid target handle")
                source_type = by_id[edge["source"]]["type"]
                if source_type == "loop":
                    self.assertIn(
                        edge.get("sourceHandle"),
                        {"loop-start-source", "loop-end-source"},
                        f"{name}: invalid loop source handle",
                    )
                elif source_type != "condition":
                    self.assertEqual("source", edge.get("sourceHandle"), f"{name}: invalid source handle")

            for item in values:
                if item["type"] != "condition":
                    continue
                options = json.loads(item["subBlocks"]["conditions"]["value"])
                expected = {f"condition-{option['id']}" for option in options}
                actual = {edge.get("sourceHandle") for edge in outgoing[item["id"]]}
                self.assertEqual(expected, actual, f"{name}/{item['name']}: condition handles")
                self.assertEqual(len(expected), len(outgoing[item["id"]]), f"{name}/{item['name']}: duplicate routes")

            loop_children: set[str] = set()
            for loop_id, loop in workflow["state"].get("loops", {}).items():
                self.assertIn(loop_id, by_id, f"{name}: missing loop block")
                self.assertEqual("loop", by_id[loop_id]["type"], f"{name}: invalid loop block type")
                children = set(loop.get("nodes", []))
                self.assertTrue(children, f"{name}/{by_id[loop_id]['name']}: empty loop")
                loop_children |= children
                start_edges = [edge for edge in outgoing[loop_id] if edge.get("sourceHandle") == "loop-start-source"]
                end_edges = [edge for edge in outgoing[loop_id] if edge.get("sourceHandle") == "loop-end-source"]
                self.assertEqual(children, {edge["target"] for edge in start_edges}, f"{name}: loop child handles")
                self.assertEqual(1, len(end_edges), f"{name}: loop must have one continuation")
                self.assertNotIn(end_edges[0]["target"], children, f"{name}: loop continuation points inside")
                for child_id in children:
                    self.assertIn(child_id, by_id, f"{name}: missing loop child")
                    self.assertTrue(by_id[child_id].get("enabled"), f"{name}: disabled loop child")
                    self.assertIn(by_id[child_id].get("type"), {"api", "function", "agent"}, f"{name}: non-executable loop child")
                    self.assertEqual(1, len(incoming[child_id]), f"{name}: loop child incoming edges")
                    self.assertEqual(loop_id, incoming[child_id][0]["source"], f"{name}: loop child parent")
                    self.assertEqual("loop-start-source", incoming[child_id][0].get("sourceHandle"), f"{name}: loop child handle")
                    self.assertEqual(loop_id, by_id[child_id].get("data", {}).get("parentId"), f"{name}: loop child data.parentId")
                    self.assertEqual("parent", by_id[child_id].get("data", {}).get("extent"), f"{name}: loop child extent")
                    position = by_id[child_id].get("position", {})
                    self.assertGreaterEqual(float(position.get("x", -1)), 0, f"{name}: loop child x")
                    self.assertLessEqual(float(position.get("x", 9999)), 500, f"{name}: loop child x")
                    self.assertGreaterEqual(float(position.get("y", -1)), 0, f"{name}: loop child y")
                    self.assertLessEqual(float(position.get("y", 9999)), 300, f"{name}: loop child y")

            starts = [item for item in values if item["type"] == "start_trigger"]
            start_id = starts[0]["id"]
            for item in values:
                if item["id"] != start_id:
                    self.assertTrue(incoming[item["id"]], f"{name}/{item['name']}: no incoming edge")
                if item["type"] != "response" and item["id"] not in loop_children:
                    self.assertTrue(outgoing[item["id"]], f"{name}/{item['name']}: no outgoing edge")

            # A SIM placeholder must refer to a block that executes on every
            # route leading to the consumer. This rejects unsafe joins such as
            # reading Create PR output on the branch where Create PR was skipped.
            all_ids = set(by_id)
            predecessors = {block_id: {edge["source"] for edge in incoming[block_id]} for block_id in all_ids}
            dominators = {block_id: ({block_id} if block_id == start_id else set(all_ids)) for block_id in all_ids}
            changed = True
            while changed:
                changed = False
                for block_id in all_ids - {start_id}:
                    preds = predecessors[block_id]
                    shared = set.intersection(*(dominators[pred] for pred in preds)) if preds else set()
                    updated = {block_id} | shared
                    if updated != dominators[block_id]:
                        dominators[block_id] = updated
                        changed = True
            for item in values:
                raw = json.dumps(item, ensure_ascii=False)
                references = {match.group(1).lower() for match in PLACEHOLDER.finditer(raw)}
                for reference in references:
                    source_id = by_slug[reference]["id"]
                    self.assertIn(
                        source_id,
                        dominators[item["id"]],
                        f"{name}/{item['name']}: branch-dependent reference to {by_slug[reference]['name']}",
                    )

    def test_functions_conditions_and_schemas_parse(self) -> None:
        valid_json_types = {"object", "array", "string", "number", "integer", "boolean", "null"}

        def check_schema(node: Any) -> None:
            if not isinstance(node, dict):
                return
            if "type" in node:
                value = node["type"]
                values = value if isinstance(value, list) else [value]
                self.assertTrue(set(values) <= valid_json_types, value)
            for child in node.values():
                if isinstance(child, dict):
                    check_schema(child)
                elif isinstance(child, list):
                    for item in child:
                        check_schema(item)

        for name, workflow in self.workflows.items():
            for item in blocks(workflow):
                if item["type"] == "function":
                    self.compile_js(str(item["subBlocks"]["code"]["value"]))
                elif item["type"] == "condition":
                    options = json.loads(item["subBlocks"]["conditions"]["value"])
                    self.assertGreaterEqual(len(options), 2, f"{name}/{item['name']}")
                    for option in options:
                        if option["value"]:
                            self.compile_js(f"return Boolean({option['value']});")
                elif item["type"] == "agent":
                    sub = item["subBlocks"]
                    self.assertEqual("qwen3-coder-next:latest", sub["model"]["value"])
                    self.assertEqual("none", sub["thinkingLevel"]["value"])
                    self.assertEqual("none", sub["reasoningEffort"]["value"])
                    schema = json.loads(sub["responseFormat"]["value"])
                    check_schema(schema)

    def test_only_essential_deterministic_guards_remain(self) -> None:
        counts = {name[:2]: len(blocks(workflow)) for name, workflow in self.workflows.items()}
        self.assertLessEqual(counts["01"], 20)
        self.assertLessEqual(counts["02"], 22)
        self.assertLessEqual(counts["03"], 45)
        self.assertLessEqual(counts["04"], 48)
        raw = "\n".join(json.dumps(value, ensure_ascii=False) for value in self.workflows.values())
        self.assertNotIn("Requirements Reviewer", raw)
        self.assertNotIn("Architecture Reviewer", raw)
        self.assertNotIn("Revision Reviewer", raw)
        self.assertNotIn("Implementation Profile Catalog", raw)
        self.assertNotIn("repair-checkpoints", raw)
        self.assertNotIn("14–30", raw)

    def test_cross_workflow_and_gitea_contracts(self) -> None:
        raw = {name[:2]: json.dumps(value, ensure_ascii=False) for name, value in self.workflows.items()}
        self.assertIn("requirements.json", raw["01"])
        self.assertIn("{{SIM_WORKFLOW02_ID}}", raw["01"])
        self.assertIn("01-requirements-demo", raw["02"])
        self.assertIn("architecture.json", raw["02"])
        self.assertIn("{{SIM_WORKFLOW03_ID}}", raw["02"])
        for path in [
            "docs/USER_GUIDE.md",
            "docs/ADMIN_GUIDE.md",
            "docs/TECHNICAL_GUIDE.md",
        ]:
            self.assertIn(path, raw["01"])
            self.assertIn(path, raw["02"])
            self.assertIn(path, raw["03"])
        self.assertIn("02-architecture-demo", raw["03"])
        self.assertIn("development-contracts", raw["03"])
        self.assertIn("ai/${runId}", raw["03"])
        self.assertIn("Test Developer", raw["03"])
        self.assertIn("Documentation Writer", raw["03"])
        self.assertIn("Generation Repair", raw["03"])
        self.assertIn("Merge Generation Repair", raw["03"])
        self.assertIn("Split Implementation Plan", raw["03"])
        self.assertIn("ci-summary.json", raw["04"])
        self.assertIn("findings.json", raw["04"])
        self.assertIn("pytest.log", raw["04"])
        self.assertIn("PYTEST LOG:", raw["04"])
        self.assertIn("Revision Safeguard", raw["04"])
        self.assertIn("Validate Final Revision", raw["04"])
        self.assertIn("no_tests_collected", raw["04"])
        self.assertIn("Исправление удаляет тестовые функции", raw["04"])
        self.assertIn("Retry CI Without Changes", raw["04"])
        self.assertIn("Autonomous Limit Reached", raw["04"])
        self.assertNotIn("next_attempt: Number(<validateinput.result.attempt>) + 1", raw["04"])
        self.assertIn("development-contract.json", raw["04"])
        self.assertIn("pipeline.yml/dispatches", raw["04"])
        for value in raw.values():
            self.assertNotRegex(value, r"(?i)(?:token|password|api[_-]?key)\s*[:=]\s*[A-Za-z0-9_-]{16,}")

    def test_core_function_paths_execute(self) -> None:
        by_prefix = {name[:2]: value for name, value in self.workflows.items()}

        init_code = named(by_prefix["01"], "Initialize Request")["subBlocks"]["code"]["value"]
        initialized = self.execute_js(
            init_code,
            {
                "<start.user_request>": "Создай небольшой FastAPI API со списком задач и тестами.",
                "<start.target_owner>": "labadmin",
                "<start.target_repo>": "demo-fastapi",
                "<start.base_branch>": "main",
                "<start.artifact_owner>": "labadmin",
                "<start.artifact_package>": "ai-demo-artifacts",
            },
        )
        self.assertTrue(initialized["valid"])
        self.assertRegex(initialized["run_id"], r"^run-\d{8}-\d{6}-[a-z0-9]{6}$")

        documentation_paths = [
            "docs/USER_GUIDE.md",
            "docs/ADMIN_GUIDE.md",
            "docs/TECHNICAL_GUIDE.md",
        ]
        documentation_requirements = [
            {
                "id": f"DOC-{index:02d}",
                "path": path,
                "audience": "Пользователь или администратор проекта",
                "content": "Содержательное описание назначения, процедур, ограничений и примеров для этого документа.",
                "acceptance": "Документ содержит проверяемые инструкции и согласован с требованиями и поведением приложения.",
            }
            for index, path in enumerate(documentation_paths, start=1)
        ]
        requirements_code = named(by_prefix["01"], "Validate Requirements")["subBlocks"]["code"]["value"]
        requirements_result = self.execute_js(
            requirements_code,
            {
                "<requirementsanalyst.summary>": "Небольшое FastAPI приложение для демонстрации",
                "<requirementsanalyst.functional_requirements>": [
                    {"id": "FR-01", "requirement": "Предоставить API", "acceptance": "Ответ HTTP 200"}
                ],
                "<requirementsanalyst.constraints>": ["Python 3.12"],
                "<requirementsanalyst.documentation_requirements>": documentation_requirements,
                "<requirementsanalyst.test_scenarios>": ["Проверить успешный запрос"],
                "<requirementsanalyst.open_questions>": [],
                "<initializerequest.result>": initialized,
            },
        )
        self.assertTrue(requirements_result["valid"], requirements_result["errors"])
        missing_document_requirement = self.execute_js(
            requirements_code,
            {
                "<requirementsanalyst.summary>": "Небольшое FastAPI приложение для демонстрации",
                "<requirementsanalyst.functional_requirements>": [
                    {"id": "FR-01", "requirement": "Предоставить API", "acceptance": "Ответ HTTP 200"}
                ],
                "<requirementsanalyst.constraints>": ["Python 3.12"],
                "<requirementsanalyst.documentation_requirements>": documentation_requirements[:-1],
                "<requirementsanalyst.test_scenarios>": ["Проверить успешный запрос"],
                "<requirementsanalyst.open_questions>": [],
                "<initializerequest.result>": initialized,
            },
        )
        self.assertFalse(missing_document_requirement["valid"])

        architecture_code = named(by_prefix["02"], "Validate Architecture")["subBlocks"]["code"]["value"]
        planned = [
            {"path": "app/__init__.py", "purpose": "package"},
            {"path": "app/main.py", "purpose": "API"},
            {"path": "app/routes.py", "purpose": "routes"},
            {"path": "tests/__init__.py", "purpose": "test package marker"},
            {"path": "tests/test_api.py", "purpose": "tests"},
            {"path": "requirements.txt", "purpose": "runtime"},
            {"path": "requirements-dev.txt", "purpose": "test dependencies"},
            *[{"path": path, "purpose": "Полная документация проекта"} for path in documentation_paths],
        ]
        architecture = self.execute_js(
            architecture_code,
            {
                "<solutionarchitect.summary>": "Компактное FastAPI приложение",
                "<solutionarchitect.architecture>": "A" * 600,
                "<solutionarchitect.files>": planned,
                "<solutionarchitect.test_strategy>": "pytest integration tests",
                "<solutionarchitect.risks>": [],
                "<validaterequirementsinput.result.artifact>": {"run_id": initialized["run_id"]},
            },
        )
        self.assertTrue(architecture["valid"], architecture["errors"])
        large_plan = planned + [
            {"path": f"app/generated/module_{index}.py", "purpose": "Дополнительный модуль"}
            for index in range(35)
        ]
        architecture_without_count_limit = self.execute_js(
            architecture_code,
            {
                "<solutionarchitect.summary>": "Расширенное FastAPI приложение",
                "<solutionarchitect.architecture>": "A" * 600,
                "<solutionarchitect.files>": large_plan,
                "<solutionarchitect.test_strategy>": "pytest integration tests",
                "<solutionarchitect.risks>": [],
                "<validaterequirementsinput.result.artifact>": {"run_id": initialized["run_id"]},
            },
        )
        self.assertTrue(architecture_without_count_limit["valid"], architecture_without_count_limit["errors"])
        architecture_without_full_docs = self.execute_js(
            architecture_code,
            {
                "<solutionarchitect.summary>": "Компактное FastAPI приложение",
                "<solutionarchitect.architecture>": "A" * 600,
                "<solutionarchitect.files>": planned[:-1],
                "<solutionarchitect.test_strategy>": "pytest integration tests",
                "<solutionarchitect.risks>": [],
                "<validaterequirementsinput.result.artifact>": {"run_id": initialized["run_id"]},
            },
        )
        self.assertFalse(architecture_without_full_docs["valid"])

        split_code = named(by_prefix["03"], "Split Implementation Plan")["subBlocks"]["code"]["value"]
        split = self.execute_js(
            split_code,
            {
                "<validateimplementationinput.result.artifact.repository_plan.files>": planned,
            },
        )
        self.assertEqual(5, len(split["application_files"]))
        self.assertEqual(2, len(split["test_files"]))
        self.assertEqual(3, len(split["documentation_files"]))

        inspect_code = named(by_prefix["03"], "Inspect Generated Files")["subBlocks"]["code"]["value"]
        generated_application = [
            {"path": item["path"], "content": "" if item["path"] == "app/__init__.py" else "ready"}
            for item in split["application_files"]
        ]
        generated_tests = [
            {
                "path": item["path"],
                "content": "" if item["path"] == "tests/__init__.py" else "def test_ready():\n    assert True\n",
            }
            for item in split["test_files"]
        ]
        document_content = "# Назначение\n\n" + ("Содержательное описание проекта. " * 30) + "\n\n## Использование\n\nИнструкция.\n\n## Ограничения\n\nОграничения."
        generated_docs = [{"path": item["path"], "content": document_content} for item in split["documentation_files"]]
        inspected = self.execute_js(
            inspect_code,
            {
                "<developer.files>": generated_application,
                "<testdeveloper.files>": generated_tests,
                "<documentationwriter.files>": generated_docs,
                "<validateimplementationinput.result.artifact.repository_plan.files>": planned,
                "<splitimplementationplan.result.application_files>": split["application_files"],
                "<splitimplementationplan.result.test_files>": split["test_files"],
                "<splitimplementationplan.result.documentation_files>": split["documentation_files"],
                "<developer.summary>": "Проект создан",
            },
        )
        self.assertTrue(inspected["valid"], inspected["errors"])

        merge_code = named(by_prefix["03"], "Merge Generation Repair")["subBlocks"]["code"]["value"]
        merged = self.execute_js(
            merge_code,
            {
                "<validateimplementationinput.result.artifact.repository_plan.files>": planned,
                "<inspectgeneratedfiles.result.files>": inspected["files"],
                "<inspectgeneratedfiles.result.valid>": inspected["valid"],
                "<generationrepair.files>": [],
                "<generationrepair.summary>": "Исправление не требуется",
            },
        )
        self.assertFalse(merged["repair_attempted"])

        files_code = named(by_prefix["03"], "Validate Generated Files")["subBlocks"]["code"]["value"]
        def validate_merged(value: dict[str, Any]) -> Any:
            return self.execute_js(
                files_code,
                {
                    "<mergegenerationrepair.result.files>": value["files"],
                    "<validateimplementationinput.result.artifact.repository_plan.files>": planned,
                    "<splitimplementationplan.result.documentation_files>": split["documentation_files"],
                    "<mergegenerationrepair.result.merge_errors>": value["merge_errors"],
                    "<mergegenerationrepair.result.repair_attempted>": value["repair_attempted"],
                    "<mergegenerationrepair.result.repaired_paths>": value["repaired_paths"],
                    "<mergegenerationrepair.result.summary>": value["summary"],
                },
            )

        validated = validate_merged(merged)
        self.assertTrue(validated["valid"], validated["errors"])

        missing_test = self.execute_js(
            inspect_code,
            {
                "<developer.files>": generated_application,
                "<testdeveloper.files>": [item for item in generated_tests if item["path"] != "tests/test_api.py"],
                "<documentationwriter.files>": generated_docs,
                "<validateimplementationinput.result.artifact.repository_plan.files>": planned,
                "<splitimplementationplan.result.application_files>": split["application_files"],
                "<splitimplementationplan.result.test_files>": split["test_files"],
                "<splitimplementationplan.result.documentation_files>": split["documentation_files"],
                "<developer.summary>": "Проект создан",
            },
        )
        self.assertFalse(missing_test["valid"])
        repaired = self.execute_js(
            merge_code,
            {
                "<validateimplementationinput.result.artifact.repository_plan.files>": planned,
                "<inspectgeneratedfiles.result.files>": missing_test["files"],
                "<inspectgeneratedfiles.result.valid>": missing_test["valid"],
                "<generationrepair.files>": [
                    {"path": "tests/test_api.py", "content": "def test_repaired():\n    assert True\n"}
                ],
                "<generationrepair.summary>": "Добавлен отсутствующий тест",
            },
        )
        self.assertTrue(repaired["repair_attempted"])
        self.assertEqual(["tests/test_api.py"], repaired["repaired_paths"])
        repaired_validation = validate_merged(repaired)
        self.assertTrue(repaired_validation["valid"], repaired_validation["errors"])

        prepare_code = named(by_prefix["03"], "Prepare Writes")["subBlocks"]["code"]["value"]
        prepared = self.execute_js(
            prepare_code,
            {
                "<validategeneratedfiles.result.files>": [
                    {"path": "docs/USER_GUIDE.md", "content": "Привет", "encoded_path": "docs/USER_GUIDE.md"}
                ],
                "<gettargetbranchtree.status>": 200,
                "<gettargetbranchtree.data.tree>": [],
            },
        )
        expected_b64 = base64.b64encode("Привет".encode("utf-8")).decode("ascii")
        self.assertEqual(expected_b64, prepared["create_files"][0]["content_base64"])

        find_pr = named(by_prefix["03"], "Find Existing PR")
        find_keys = {
            row["cells"]["Key"]
            for row in find_pr["subBlocks"]["params"]["value"]
        }
        self.assertEqual({"state", "page", "limit"}, find_keys)
        create_pr = named(by_prefix["03"], "Create PR")
        create_headers = {
            row["cells"]["Key"].lower()
            for row in create_pr["subBlocks"]["headers"]["value"]
        }
        self.assertIn("content-type", create_headers)

        resolve_pr_code = named(by_prefix["03"], "Resolve Existing PR")["subBlocks"]["code"]["value"]
        old_pr = {
            "number": 11,
            "state": "open",
            "html_url": "https://gitea.invalid/pulls/11",
            "head": {"ref": "ai/run-old"},
            "base": {"ref": "main"},
        }
        matching_pr = {
            "number": 22,
            "state": "open",
            "html_url": "https://gitea.invalid/pulls/22",
            "head": {"ref": "ai/run-current"},
            "base": {"ref": "main"},
        }
        common_pr_replacements = {
            "<findexistingpr.status>": 200,
            "<validateimplementationinput.result.branch>": "ai/run-current",
            "<validateimplementationinput.result.base_branch>": "main",
            "<validateimplementationinput.result.run_id>": "run-current",
            "<validategeneratedfiles.result.files>": [{"path": "app/main.py"}],
        }
        no_match = self.execute_js(
            resolve_pr_code,
            {**common_pr_replacements, "<findexistingpr.data>": [old_pr]},
        )
        self.assertFalse(no_match["found"])
        exact_match = self.execute_js(
            resolve_pr_code,
            {**common_pr_replacements, "<findexistingpr.data>": [old_pr, matching_pr]},
        )
        self.assertTrue(exact_match["found"])
        self.assertEqual(22, exact_match["result"]["pr_number"])

        select_code = named(by_prefix["04"], "Select Revision Paths")["subBlocks"]["code"]["value"]
        selected = self.execute_js(
            select_code,
            {
                "<buildcicontext.result.approved_paths>": ["app/main.py", "tests/test_api.py"],
                "<buildcicontext.result.no_tests_collected>": False,
                "<ciresultanalyst.files>": ["app/main.py", ".gitea/workflows/pipeline.yml"],
            },
        )
        self.assertTrue(selected["valid"])
        self.assertEqual(
            ["app/main.py", "tests/test_api.py"],
            [item["path"] for item in selected["paths"]],
        )

        selected_for_exit_five = self.execute_js(
            select_code,
            {
                "<buildcicontext.result.approved_paths>": ["app/main.py", "tests/test_api.py"],
                "<buildcicontext.result.no_tests_collected>": True,
                "<ciresultanalyst.files>": ["app/main.py"],
            },
        )
        self.assertTrue(selected_for_exit_five["valid"])
        self.assertEqual("tests/test_api.py", selected_for_exit_five["paths"][0]["path"])

        ci_context_code = named(by_prefix["04"], "Build CI Context")["subBlocks"]["code"]["value"]
        ci_context = self.execute_js(
            ci_context_code,
            {
                "<getcisummary.data>": {
                    "quality_gate": {"passed": False},
                    "stages": [{"name": "pytest", "exit_code": 5}],
                },
                "<getcisummary.status>": 200,
                "<getfindings.data>": [],
                "<getfindings.status>": 200,
                "<getpytestlog.data>": "collected 0 items\n\nno tests ran in 0.01s",
                "<getpytestlog.status>": 200,
                "<getdevelopmentcontract.data>": {
                    "owner": "labadmin",
                    "repo": "demo-fastapi",
                    "repository_plan": {"files": planned},
                },
                "<getdevelopmentcontract.status>": 200,
                "<validateinput.result.owner>": "labadmin",
                "<validateinput.result.repo>": "demo-fastapi",
            },
        )
        self.assertTrue(ci_context["valid"], ci_context["errors"])
        self.assertTrue(ci_context["no_tests_collected"])
        self.assertFalse(ci_context["transient_failure"])

        validate_revision_code = named(by_prefix["04"], "Validate Revision")["subBlocks"]["code"]["value"]
        current_test = (
            "def reset_state():\n    pass\n\n"
            "def test_create():\n    assert True\n\n"
            "def test_list():\n    assert True\n"
        )
        fixture_only = self.execute_js(
            validate_revision_code,
            {
                "<revisiondeveloper.files>": [
                    {"path": "tests/test_api.py", "content": "def reset_state():\n    pass\n"}
                ],
                "<buildrevisioncontext.result.files>": [
                    {"path": "tests/test_api.py", "content": current_test, "sha": "abc"}
                ],
                "<buildcicontext.result.no_tests_collected>": True,
                "<revisiondeveloper.summary>": "Исправлен reset_state",
            },
        )
        self.assertFalse(fixture_only["valid"])
        self.assertTrue(any("def test_*" in item for item in fixture_only["errors"]))

        preserved_tests = self.execute_js(
            validate_revision_code,
            {
                "<revisiondeveloper.files>": [
                    {
                        "path": "tests/test_api.py",
                        "content": current_test.replace("pass", "from app import main\n    main.id_counter = 0"),
                    }
                ],
                "<buildrevisioncontext.result.files>": [
                    {"path": "tests/test_api.py", "content": current_test, "sha": "abc"}
                ],
                "<buildcicontext.result.no_tests_collected>": True,
                "<revisiondeveloper.summary>": "Исправлен reset_state без удаления тестов",
            },
        )
        self.assertTrue(preserved_tests["valid"], preserved_tests["errors"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
