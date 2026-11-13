from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORKFLOWS = HERE / "workflows"


def load_workflow(prefix: str) -> dict[str, object]:
    path = next(WORKFLOWS.glob(f"{prefix}-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def named_block(workflow: dict[str, object], name: str) -> dict[str, object]:
    blocks = workflow["state"]["blocks"].values()  # type: ignore[index,union-attr]
    matches = [item for item in blocks if item.get("name") == name]
    if len(matches) != 1:
        raise AssertionError(f"{name}: expected one block, got {len(matches)}")
    return matches[0]


class DownstreamWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("Node.js is not installed")
        cls.w2 = load_workflow("02")
        cls.w3 = load_workflow("03")
        cls.w4 = load_workflow("04")

    def execute_js(
        self,
        code: str,
        replacements: dict[str, object],
        *,
        expect_success: bool = True,
    ) -> object | None:
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
        runner = """
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const fn = new Function(input.code);
const result = fn();
process.stdout.write(JSON.stringify(result));
"""
        execution = subprocess.run(
            [self.node, "-e", runner],
            input=json.dumps({"code": normalized}, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if expect_success:
            self.assertEqual(0, execution.returncode, execution.stderr)
            return json.loads(execution.stdout)
        self.assertNotEqual(0, execution.returncode)
        return None

    def test_architecture_approve_is_closed_when_review_failed(self) -> None:
        code = named_block(self.w2, "Normalize Architecture Decision")["subBlocks"][
            "code"
        ]["value"]
        blocked = self.execute_js(
            code,
            {
                "<architectureapproval.decision>": "approve",
                "<architectureapproval.comments>": "",
                "<validatearchitecturereview.result.review.passed>": False,
            },
        )
        self.assertFalse(blocked["valid"])
        self.assertIn("Approve запрещён", blocked["error"])

        revise = self.execute_js(
            code,
            {
                "<architectureapproval.decision>": "revise",
                "<architectureapproval.comments>": "Исправить замечания reviewer",
                "<validatearchitecturereview.result.review.passed>": False,
            },
        )
        self.assertTrue(revise["valid"])

    def test_complete_verbose_architecture_fits_safety_ceiling(self) -> None:
        architect = named_block(self.w2, "Solution Architect")
        prompt = "\n".join(
            str(item.get("content", ""))
            for item in architect["subBlocks"]["messages"]["value"]
        )
        self.assertIn("до 18000 символов", prompt)

        code = named_block(self.w2, "Validate Architecture Output")["subBlocks"][
            "code"
        ]["value"]
        marker = "<!-- COMPLETE:ARCHITECTURE -->"
        complete = "# Архитектура\n" + ("а" * (17902 - len(marker) - 16)) + marker
        accepted = self.execute_js(
            code,
            {"<solutionarchitect.content>": complete},
        )
        self.assertTrue(accepted["valid"], accepted["errors"])

        oversized = ("а" * 22001) + marker
        rejected = self.execute_js(
            code,
            {"<solutionarchitect.content>": oversized},
        )
        self.assertFalse(rejected["valid"])
        self.assertIn("Архитектура превышает 22000 символов", rejected["errors"])

    def test_existing_target_branch_is_recovered_from_branch_list(self) -> None:
        code = named_block(self.w3, "Check Created Branch")["subBlocks"]["code"][
            "value"
        ]
        sha = "a" * 40
        result = self.execute_js(
            code,
            {
                "<gettargetbranch.data>": [
                    {"name": "main", "commit": {"id": "b" * 40}},
                    {"name": "ai/run-20260805-010203-abc123", "commit": {"id": sha}},
                ],
                "<validateimplementationinput.result.branch>": "ai/run-20260805-010203-abc123",
                "<getcreatedbranch.data>": None,
                "<gettargetbranch.status>": 200,
                "<getcreatedbranch.status>": None,
            },
        )
        self.assertTrue(result["valid"])
        self.assertTrue(result["existing"])
        self.assertEqual(sha, result["commit_sha"])

    def test_new_target_branch_is_verified_after_creation(self) -> None:
        code = named_block(self.w3, "Check Created Branch")["subBlocks"]["code"][
            "value"
        ]
        sha = "c" * 40
        result = self.execute_js(
            code,
            {
                "<gettargetbranch.data>": [{"name": "main", "commit": {"id": "b" * 40}}],
                "<validateimplementationinput.result.branch>": "ai/run-20260805-010203-abc123",
                "<getcreatedbranch.data>": {
                    "name": "ai/run-20260805-010203-abc123",
                    "commit": {"id": sha},
                },
                "<gettargetbranch.status>": 200,
                "<getcreatedbranch.status>": 200,
            },
        )
        self.assertTrue(result["valid"])
        self.assertFalse(result["existing"])
        self.assertEqual(sha, result["commit_sha"])

    def test_recheck_ci_dispatch_requires_success_and_run_id(self) -> None:
        code = named_block(self.w4, "Check Recheck CI Dispatch")["subBlocks"][
            "code"
        ]["value"]
        detailed = self.execute_js(
            code,
            {
                "<triggerrecheckci.status>": 200,
                "<triggerrecheckci.data>": {
                    "id": 42,
                    "html_url": "https://gitea.example/actions/runs/42",
                },
            },
        )
        self.assertEqual(42, detailed["workflow_run_id"])

        legacy = self.execute_js(
            code,
            {
                "<triggerrecheckci.status>": 204,
                "<triggerrecheckci.data>": None,
            },
        )
        self.assertTrue(legacy["valid"])
        self.assertIsNone(legacy["workflow_run_id"])

        self.execute_js(
            code,
            {
                "<triggerrecheckci.status>": 200,
                "<triggerrecheckci.data>": {},
            },
            expect_success=False,
        )


if __name__ == "__main__":
    unittest.main()
