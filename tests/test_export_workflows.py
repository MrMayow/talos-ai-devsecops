from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.export_workflows import ROOT, configure, export, validate_target


class ExportTests(unittest.TestCase):
    def test_rejects_paths_and_template_injection(self):
        for value in ["../owner", "owner/repo", "x{{TOKEN}}", "x';return 1", "-owner", "a..b", "repo.git"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_target(value, "application")

    def test_accepts_regular_gitea_names(self):
        validate_target("team-name", "notes_api.v1")

    def test_changes_target_in_embedded_code_and_fields(self):
        value = {"target": "labadmin/demo-fastapi", "code": "if (owner !== 'labadmin') return false;", "count": 5}
        result = configure(value, "team", "notes")
        self.assertEqual("team/notes", result["target"])
        self.assertIn("owner !== 'team'", result["code"])
        self.assertEqual(5, result["count"])

    def test_preserves_secret_and_connection_placeholders(self):
        original = {"authorization": "token {{GITEA_TOKEN}}", "url": "{{SIM_INTERNAL_URL}}/api/workflows/{{SIM_WORKFLOW03_ID}}/execute"}
        self.assertEqual(original, configure(original, "team", "notes"))

    def test_exports_both_profiles_without_changing_templates(self):
        paths = sorted((ROOT / "profiles").glob("*/workflows/*.json"))
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        with tempfile.TemporaryDirectory() as temporary:
            for profile in ["strict", "demo"]:
                output = export(profile, "team", "notes", Path(temporary) / profile)
                self.assertEqual(4, len(output))
                for path in output:
                    text = path.read_text(encoding="utf-8")
                    self.assertIn("state", json.loads(text))
                    self.assertNotIn("labadmin", text)
                    self.assertNotIn("demo-fastapi", text)
                    self.assertIn("{{GITEA_TOKEN}}", text)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_invalid_export_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "invalid"
            with self.assertRaises(ValueError):
                export("demo", "../../other", "app", output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
