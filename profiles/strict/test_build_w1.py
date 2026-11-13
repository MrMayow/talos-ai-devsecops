from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import unittest
from collections import defaultdict, deque
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("build_w1", HERE / "build_w1.py")
assert SPEC and SPEC.loader
BUILD_W1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_W1)


class Workflow01BuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = BUILD_W1.build_workflow()
        BUILD_W1.validate_built_workflow(cls.workflow)
        cls.blocks = list(cls.workflow["state"]["blocks"].values())
        cls.by_name = {item["name"]: item for item in cls.blocks}

    def execute_js(self, code: str, replacements: dict[str, object]) -> object:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js не установлен")
        normalized = code
        for placeholder, value in replacements.items():
            normalized = normalized.replace(
                placeholder,
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            )
        unresolved = re.findall(
            r"<[a-z0-9]+(?:\.[A-Za-z0-9_]+)+>", normalized, re.IGNORECASE
        )
        self.assertEqual([], unresolved)
        execution = subprocess.run(
            [
                node,
                "-e",
                "const fn=new Function(process.argv[1]); console.log(JSON.stringify(fn()));",
                normalized,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, execution.returncode, execution.stderr)
        return json.loads(execution.stdout)

    def test_api_only_defaults_and_model_policy(self) -> None:
        raw = json.dumps(self.workflow, ensure_ascii=False)
        self.assertIn("labadmin", raw)
        self.assertIn("demo-fastapi", raw)
        self.assertIn("python-fastapi-3.12", raw)
        self.assertNotIn("demo-python-cli", raw)
        agents = [item for item in self.blocks if item["type"] == "agent"]
        self.assertEqual(3, len(agents))
        for agent in agents:
            sub = agent["subBlocks"]
            self.assertEqual(BUILD_W1.MODEL, sub["model"]["value"])
            self.assertEqual("none", sub["thinkingLevel"]["value"])
            self.assertEqual("none", sub["reasoningEffort"]["value"])
            self.assertNotIn("/no_think", json.dumps(sub["messages"]["value"], ensure_ascii=False))

    def test_repair_is_checkpointed_not_unrolled(self) -> None:
        names = set(self.by_name)
        self.assertIn("Requirements Repair", names)
        self.assertIn("Publish Requirements Checkpoint", names)
        self.assertIn("Trigger Workflow 01 Repair", names)
        self.assertIn("Checkpoint Newly Published", names)
        self.assertIn("Repair Already Scheduled", names)
        self.assertFalse(
            any(re.match(r"Requirements (Repair|Reviewer) [1-5]$", name) for name in names)
        )
        continuation = self.by_name["Build Requirements Continuation"]["subBlocks"]["code"]["value"]
        self.assertIn("currentAttempt < 5", continuation)
        self.assertIn("stalled_candidate", continuation)
        self.assertIn("candidate_hash", continuation)
        publication_check = self.by_name["Check Checkpoint Publication"]["subBlocks"]["code"]["value"]
        self.assertIn("newly_created: status !== 409", publication_check)

    def test_gitea_package_write_is_preflighted_before_model(self) -> None:
        preflight = self.by_name["Verify Gitea Package Write"]
        self.assertEqual("api", preflight["type"])
        self.assertEqual("PUT", preflight["subBlocks"]["method"]["value"])
        self.assertEqual("0", preflight["subBlocks"]["retries"]["value"])
        self.assertIn("/api/packages/", preflight["subBlocks"]["url"]["value"])
        headers = {
            row["cells"]["Key"].lower(): row["cells"]["Value"]
            for row in preflight["subBlocks"]["headers"]["value"]
        }
        self.assertEqual("token {{GITEA_TOKEN}}", headers["authorization"])

        id_to_name = {item["id"]: item["name"] for item in self.blocks}
        edges = {
            (id_to_name[edge["source"]], id_to_name[edge["target"]])
            for edge in self.workflow["state"]["edges"]
        }
        self.assertIn(("Input Valid", "Verify Gitea Package Write"), edges)
        self.assertIn(("Verify Gitea Package Write", "Execution Mode"), edges)
        self.assertNotIn(("Input Valid", "Execution Mode"), edges)

    def test_all_post_requests_are_async_and_not_retried(self) -> None:
        posts = [
            item
            for item in self.blocks
            if item["type"] == "api" and item["subBlocks"]["method"]["value"] == "POST"
        ]
        self.assertEqual(3, len(posts))
        for item in posts:
            self.assertEqual("0", item["subBlocks"]["retries"]["value"])
            headers = {
                row["cells"]["Key"].lower(): row["cells"]["Value"]
                for row in item["subBlocks"]["headers"]["value"]
            }
            self.assertEqual("async", headers.get("x-execution-mode"))

    def test_approval_is_guarded_by_quality_gate(self) -> None:
        normalize = self.by_name["Normalize Decision"]["subBlocks"]["code"]["value"]
        approved = self.by_name["Build Approved Result"]["subBlocks"]["code"]["value"]
        human_candidate = self.by_name["Build Requirements Human Candidate"]["subBlocks"]["code"]["value"]
        self.assertIn("Approve запрещён", normalize)
        self.assertIn("candidate.quality_gate.passed !== true", approved)
        self.assertIn("QUALITY GATE НЕ ПРОЙДЕН", human_candidate)
        self.assertIn("approval_available", human_candidate)

    def test_initial_and_repair_routes_reach_candidate_selector(self) -> None:
        id_to_name = {item["id"]: item["name"] for item in self.blocks}
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in self.workflow["state"]["edges"]:
            adjacency[id_to_name[edge["source"]]].add(id_to_name[edge["target"]])

        def reachable(source: str, target: str) -> bool:
            queue = deque([source])
            seen = set()
            while queue:
                current = queue.popleft()
                if current == target:
                    return True
                if current in seen:
                    continue
                seen.add(current)
                queue.extend(adjacency[current] - seen)
            return False

        self.assertTrue(reachable("Requirements Analyst", "Select Active Candidate"))
        self.assertTrue(reachable("Requirements Repair", "Select Active Candidate"))
        self.assertTrue(reachable("Select Active Candidate", "Requirements Approval"))
        self.assertTrue(reachable("Select Active Candidate", "Automatic Repair Scheduled"))

    def test_embedded_javascript_parses(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js не установлен")
        placeholder = re.compile(r"<[a-z0-9]+(?:\.[A-Za-z0-9_]+)+>", re.IGNORECASE)
        failures: list[str] = []
        for item in self.blocks:
            scripts: list[tuple[str, str]] = []
            if item["type"] == "function":
                scripts.append((item["name"], item["subBlocks"]["code"]["value"]))
            elif item["type"] == "condition":
                for condition in json.loads(item["subBlocks"]["conditions"]["value"]):
                    if condition["value"]:
                        scripts.append(
                            (
                                f"{item['name']}/{condition['title']}",
                                f"return Boolean({condition['value']})",
                            )
                        )
            for label, script in scripts:
                normalized = placeholder.sub("null", script)
                check = subprocess.run(
                    [node, "-e", "new Function(process.argv[1])", normalized],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                if check.returncode:
                    failures.append(f"{label}: {check.stderr.strip()}")
        self.assertEqual([], failures)

    def test_renderer_produces_complete_valid_markdown(self) -> None:
        data = {
            "purpose": "Создать проверяемое веб-API для тестового сценария.",
            "scope": ["Веб-API; источник: user_request."],
            "actors": ["Локальный клиент API; источник: user_request."],
            "user_scenarios": [
                {"id": "US01", "description": "Клиент запрашивает состояние сервиса.", "source": "user_request"}
            ],
            "functional_requirements": [
                {
                    "id": "FR1",
                    "statement": "Система предоставляет состояние сервиса.",
                    "source": "user_request",
                    "acceptance_criteria": [
                        "При доступном сервисе запрос состояния возвращает наблюдаемый успешный ответ."
                    ],
                }
            ],
            "non_functional_requirements": [],
            "api_endpoints": [
                {
                    "id": "API1",
                    "method": "GET",
                    "path": "/status",
                    "description": "Вернуть состояние сервиса.",
                    "source": "user_request",
                    "acceptance_criteria": ["Ответ содержит состояние сервиса."],
                }
            ],
            "interfaces_and_data": [],
            "error_handling": [],
            "security_requirements": [],
            "implementation_constraints": [],
            "development_and_verification": [],
            "test_plan": [
                {
                    "id": "TP1",
                    "requirement_ids": ["FR1"],
                    "scenario": "Вызвать проверку состояния на запущенном сервисе.",
                    "expected_result": "Получен успешный ответ состояния сервиса.",
                }
            ],
            "overall_acceptance": ["FR-001 подтверждён тестом T-001."],
            "documentation": [],
            "assumptions": [],
            "open_questions": [],
            "traceability": [
                {"requirement_id": "FR1", "source": "user_request", "test_ids": ["TP1"]}
            ],
            "change_summary": ["Создана первая редакция требований."],
        }
        replacements = {
            f"<requirementsanalyst.{field}>": data[field]
            for field in BUILD_W1.DATA_FIELDS
        }
        replacements["<resolvegenerationcontext.result>"] = {
            "run_id": "run-20260802-120000-abcdef",
            "revision": 1,
            "repair_attempt": 0,
            "automation_mode": "initial",
        }
        result = self.execute_js(
            self.by_name["Render Initial Requirements"]["subBlocks"]["code"]["value"],
            replacements,
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["document"].endswith("<!-- COMPLETE:REQUIREMENTS -->"))
        self.assertIn("# Матрица трассировки требований", result["document"])
        self.assertRegex(result["candidate_hash"], r"^[a-f0-9]{8}$")
        normalized = result["requirements_data"]
        self.assertEqual("US-001", normalized["user_scenarios"][0]["id"])
        self.assertEqual("FR-001", normalized["functional_requirements"][0]["id"])
        self.assertEqual("API-001", normalized["api_endpoints"][0]["id"])
        self.assertEqual("T-001", normalized["test_plan"][0]["id"])
        self.assertEqual(["FR-001"], normalized["test_plan"][0]["requirement_ids"])
        self.assertEqual("FR-001", normalized["traceability"][0]["requirement_id"])
        self.assertEqual(["T-001"], normalized["traceability"][0]["test_ids"])

    def test_continuation_advances_once_and_stops_on_stalled_hash(self) -> None:
        candidate = {
            "valid": False,
            "errors": ["FR-001: отсутствует критерий приёмки."],
            "requirements_data": {"functional_requirements": []},
            "document": "# Неполный документ",
            "candidate_hash": "deadbeef",
            "context": {
                "run_id": "run-20260802-120000-abcdef",
                "revision": 1,
                "repair_attempt": 1,
                "automation_mode": "repair",
                "previous_candidate_hash": "feedface",
                "artifact_owner": "ai-devsecops",
                "artifact_package": "ai-workflow-artifacts",
                "target_owner": "labadmin",
                "target_repo": "demo-fastapi",
                "base_branch": "main",
                "profile_id": "python-fastapi-3.12",
                "user_request": "Создать API состояния сервиса",
            },
        }
        review_state = {
            "valid": True,
            "errors": [],
            "review": {
                "passed": False,
                "blocking_issues": [],
                "non_blocking_notes": [],
                "summary": "Документ структурно не завершён.",
            },
        }
        code = self.by_name["Build Requirements Continuation"]["subBlocks"]["code"]["value"]
        result = self.execute_js(
            code,
            {
                "<selectactivecandidate.result>": candidate,
                "<normalizerequirementsreview.result>": review_state,
            },
        )
        self.assertTrue(result["can_continue"])
        self.assertEqual(2, result["next_attempt"])
        checkpoint = json.loads(result["checkpoint_json"])
        self.assertEqual(2, checkpoint["next_attempt"])

        candidate["context"]["previous_candidate_hash"] = "deadbeef"
        stalled = self.execute_js(
            code,
            {
                "<selectactivecandidate.result>": candidate,
                "<normalizerequirementsreview.result>": review_state,
            },
        )
        self.assertTrue(stalled["stalled"])
        self.assertFalse(stalled["can_continue"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
