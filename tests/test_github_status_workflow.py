from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "status-dry-run.yml"


class GithubStatusWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_is_manual_only(self):
        self.assertIn("workflow_dispatch:", self.text)
        self.assertNotIn("schedule:", self.text)
        self.assertNotIn("cron:", self.text)

    def test_workflow_has_read_only_repository_permission(self):
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertIn("persist-credentials: false", self.text)
        self.assertNotIn("contents: write", self.text)

    def test_workflow_runs_only_fixed_dry_run_limit(self):
        self.assertIn("python scripts/status_dry_run.py --limit 5", self.text)
        self.assertNotIn("--write", self.text)
        self.assertNotIn("save_manual", self.text)

    def test_turbosms_secret_is_not_available_to_workflow(self):
        self.assertNotIn("TURBOSMS", self.text.upper())

    def test_required_secrets_are_references_not_values(self):
        for key in (
            "GCP_SERVICE_ACCOUNT_JSON",
            "NOVA_POSHTA_API_KEY",
            "UP_TRACKING_TOKEN",
        ):
            self.assertIn(f"${{{{ secrets.{key} }}}}", self.text)
        self.assertNotIn("private_key_id", self.text)
        self.assertNotIn("BEGIN PRIVATE KEY", self.text)


if __name__ == "__main__":
    unittest.main()
