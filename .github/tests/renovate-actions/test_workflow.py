"""Validate the caller/action boundary; GitHub execution is a separate live gate."""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]


def read_yaml(path):
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = read_yaml(ROOT / ".github/workflows/renovate-config-lint.yaml")

    def test_all_three_jobs_call_local_actions_after_checkout(self):
        jobs = self.workflow["jobs"]
        self.assertEqual(set(jobs), {"validate-renovate-config", "lookup-renovate-dependencies", "monitor-renovate"})
        for job_id, action in [
            ("validate-renovate-config", "validate"),
            ("lookup-renovate-dependencies", "lookup"),
            ("monitor-renovate", "monitor"),
        ]:
            with self.subTest(job=job_id):
                steps = jobs[job_id]["steps"]
                matches = [i for i, step in enumerate(steps)
                           if step.get("uses") == f"./.github/actions/renovate-{action}"]
                self.assertEqual(len(matches), 1)
                checkout = [i for i, step in enumerate(steps)
                            if step.get("uses", "").startswith("actions/checkout@")]
                self.assertTrue(checkout and checkout[0] < matches[0])
                self.assertEqual(steps[checkout[0]]["with"]["persist-credentials"], "false")

    def test_reason_outputs_and_whole_job_results_reach_monitor(self):
        jobs = self.workflow["jobs"]
        for job_id, step_id in [("validate-renovate-config", "validate"), ("lookup-renovate-dependencies", "lookup")]:
            self.assertEqual(jobs[job_id]["outputs"]["reason"], f"${{{{ steps.{step_id}.outputs.reason }}}}")
            self.assertTrue(any(step.get("id") == step_id for step in jobs[job_id]["steps"]))
        monitor = jobs["monitor-renovate"]
        self.assertEqual(set(monitor["needs"]), {"validate-renovate-config", "lookup-renovate-dependencies"})
        call = next(step for step in monitor["steps"] if step.get("uses", "").endswith("renovate-monitor"))
        for prefix, job_id in [("validation", "validate-renovate-config"), ("lookup", "lookup-renovate-dependencies")]:
            self.assertEqual(call["with"][f"{prefix}-result"], f"${{{{ needs.{job_id}.result }}}}")
            self.assertEqual(call["with"][f"{prefix}-reason"], f"${{{{ needs.{job_id}.outputs.reason }}}}")
        self.assertFalse(any(step.get("continue-on-error") == "true" for step in jobs["validate-renovate-config"]["steps"]))

    def test_permissions_events_and_action_change_triggers(self):
        self.assertEqual(self.workflow.get("permissions"), {})
        jobs = self.workflow["jobs"]
        self.assertNotIn("if", jobs["validate-renovate-config"])
        for job_id in ["lookup-renovate-dependencies", "monitor-renovate"]:
            condition = jobs[job_id]["if"]
            self.assertIn("vars.RENOVATE_HEALTH_CHECK != 'false'", condition)
            self.assertIn("github.event_name == 'schedule'", condition)
            self.assertIn("github.event_name == 'workflow_dispatch'", condition)
        self.assertIn("!cancelled()", jobs["monitor-renovate"]["if"])
        self.assertEqual(jobs["monitor-renovate"]["concurrency"]["cancel-in-progress"], "false")
        for job_id in ["validate-renovate-config", "lookup-renovate-dependencies"]:
            self.assertEqual(jobs[job_id]["permissions"], {"contents": "read"})
        self.assertEqual(jobs["monitor-renovate"]["permissions"], {"contents": "read", "issues": "write"})
        for event in ["push", "pull_request"]:
            paths = self.workflow["on"][event]["paths"]
            for action in ["validate", "lookup", "monitor"]:
                self.assertIn(f".github/actions/renovate-{action}/**", paths)
            self.assertIn(".github/tests/renovate-actions/**", paths)

    def test_composite_metadata_exports_existing_step_outputs(self):
        for action in ["validate", "lookup", "monitor"]:
            metadata_path = ROOT / f".github/actions/renovate-{action}/action.yml"
            self.assertTrue(metadata_path.exists())
            metadata = read_yaml(metadata_path)
            self.assertEqual(metadata["runs"]["using"], "composite")
            steps = metadata["runs"]["steps"]
            self.assertTrue(all(step["shell"] == "bash" for step in steps))
            if action != "monitor":
                self.assertEqual(metadata["outputs"]["reason"]["value"], f"${{{{ steps.{action}.outputs.reason }}}}")
                self.assertTrue(any(step.get("id") == action for step in steps))
            else:
                self.assertEqual(set(metadata["inputs"]), {
                    "validation-result", "lookup-result", "validation-reason", "lookup-reason",
                })
                for prefix in ["validation", "lookup"]:
                    self.assertEqual(metadata["inputs"][f"{prefix}-result"]["required"], "true")
                    self.assertEqual(metadata["inputs"][f"{prefix}-reason"]["default"], "")
