"""End-to-end collection and rendering against a fake platform."""

import unittest
from datetime import datetime, timedelta, timezone

from radar.collect import collect_application
from radar.config import ApplicationConfig, ComponentConfig, Defaults
from radar.model import Change, ReadyPR, Release, ReleaseAction
from radar.render import issue_title, render

NOW = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)


class FakePlatform:
    """A Platform implementation backed by literals, not HTTP."""

    def __init__(self, data):
        self.data = data
        self.published = []

    def latest_release(self, repo):
        return self.data[repo]["release"]

    def changes_since(self, repo, since):
        return list(self.data[repo]["changes"])

    def ready_prs(self, repo):
        ready = list(self.data[repo]["ready"])
        return ready, self.data[repo]["open"]

    def changed_paths(self, repo, number):
        return self.data[repo].get("paths", {}).get(number, ["src/main.go"])

    def release_action(self, repo, method, workflow, version):
        if not self.data[repo].get("action"):
            return None
        return ReleaseAction(label=f"Run {workflow}", url=f"https://x/{repo}")

    def upsert_issue(self, repo, label, title, body):
        self.published.append((repo, label, title))
        return f"https://x/{repo}/issues/1"


def change(number, title, labels=None):
    """Build a merged change."""
    return Change(
        number=number,
        title=title,
        url=f"https://x/{number}",
        author="dev",
        labels=labels or [],
    )


def ready(number, title, idle, labels=None):
    """Build an open request that is ready to merge."""
    return ReadyPR(
        number=number,
        title=title,
        url=f"https://x/{number}",
        repo="Netcracker/qubership-monitoring-operator",
        idle_days=idle,
        labels=labels or [],
    )


def build_report():
    """Collect a two-component application from fake data."""
    data = {
        "Netcracker/qubership-monitoring-operator": {
            "release": Release(
                tag="v0.88.1",
                url="https://x/rel",
                published=NOW - timedelta(days=4),
                age_days=4,
            ),
            "changes": [
                change(506, "fix: allow disabling Grafana", ["bug"]),
                change(494, "fix: pin operator images"),
                change(512, "chore(deps): update golang docker tag", ["dependencies"]),
                change(482, "fix(ci): ignore Renovate notices", ["bug"]),
            ],
            "ready": [
                ready(365, "feat: added k8s deployment hardening tests", 77),
                ready(511, "fix(helm): render empty remoteWrite list", 3),
            ],
            "open": 23,
            "action": True,
            "paths": {
                506: ["charts/qubership-monitoring-operator/Chart.yaml"],
                494: ["docker-compose.yaml"],
            },
        },
        "Netcracker/qubership-grafana-reporter": {
            "release": Release(
                tag="0.1.1",
                url="https://x/rel2",
                published=NOW - timedelta(days=492),
                age_days=492,
            ),
            "changes": [
                change(78, "feat: Add security scan workflow for Docker packages"),
                change(135, "fix(ci): ignore Renovate notices", ["bug"]),
                change(137, "chore(deps): update golang docker tag", ["dependencies"]),
            ],
            "ready": [],
            "open": 2,
            "action": False,
            "paths": {
                # qubership-grafana-reporter#78: a `feat:` title on a request
                # that touches nothing but CI configuration.
                78: [".github/workflows/security-scan.yml", ".qubership/docker.cfg"],
            },
        },
    }
    spec = ApplicationConfig(
        id="monitoring",
        title="Monitoring",
        issue_label="radar/monitoring",
        components=[
            ComponentConfig(repo=repo, release_workflow="docker-release.yaml")
            for repo in data
        ],
    )
    platform = FakePlatform(data)
    return collect_application(platform, spec, Defaults(), now=NOW)


class Collection(unittest.TestCase):
    """The collector separates releasable work from noise."""

    def setUp(self):
        self.report = build_report()
        self.operator, self.reporter = self.report.components

    def test_only_user_facing_changes_are_releasable(self):
        self.assertEqual([c.number for c in self.operator.changes], [506, 494])
        self.assertEqual([c.number for c in self.operator.dependencies], [512])
        self.assertEqual([c.number for c in self.operator.internal], [482])

    def test_next_version_is_a_patch(self):
        self.assertEqual(self.operator.next_version, "v0.88.2")

    def test_ready_features_project_a_minor_release(self):
        self.assertEqual(self.operator.projected_version, "v0.89.0")

    def test_ci_only_feat_is_demoted_by_its_file_paths(self):
        # Neither the label nor the title reveals this: only the paths do.
        self.assertFalse(self.reporter.releasable)
        self.assertIn(78, [c.number for c in self.reporter.internal])

    def test_component_with_only_noise_has_nothing_to_release(self):
        self.assertFalse(self.reporter.releasable)
        self.assertIsNone(self.reporter.next_version)

    def test_old_release_is_stale(self):
        self.assertTrue(self.reporter.stale)
        self.assertFalse(self.operator.stale)


class Rendering(unittest.TestCase):
    """The issue body carries every section the design calls for."""

    def setUp(self):
        self.report = build_report()
        self.body = render(self.report, stale_after=45, limit=3)

    def test_title(self):
        self.assertEqual(issue_title(self.report), "\U0001f4e1 Release radar: Monitoring")

    def test_headline_counts_releasable_components(self):
        self.assertIn("**1 of 2 components have releasable changes.**", self.body)

    def test_release_line_shows_the_computed_version(self):
        self.assertIn("→ **`v0.88.2`** (patch)", self.body)

    def test_unlabeled_change_is_flagged(self):
        self.assertIn("#494", self.body)
        self.assertIn("⚠️ classified from `fix:` title", self.body)

    def test_projection_warns_about_the_stronger_bump(self):
        self.assertIn("would make the next release **`v0.89.0`** (minor)", self.body)

    def test_application_wide_ready_table_is_sorted_by_idle(self):
        table = self.body.split("## Ready to merge across Monitoring")[1]
        self.assertLess(table.index("#365"), table.index("#511"))

    def test_stale_component_is_reported(self):
        self.assertIn("## Stale", self.body)
        self.assertIn("492 days ago", self.body)

    def test_quiet_component_is_not_nagged_about_a_release_workflow(self):
        # qubership-grafana-reporter has no release action and nothing to
        # release: the radar stays quiet rather than reporting a false gap.
        self.assertNotIn("Collection problems", self.body)


class MissingReleaseEntryPoint(unittest.TestCase):
    """A component that could be released but has nowhere to click."""

    def setUp(self):
        report = build_report()
        report.components = [report.components[0]]
        report.components[0].release_action = None
        report.components[0].errors.append(
            "no release entry point found (method `workflow`, "
            "workflow `docker-release.yaml`)"
        )
        self.body = render(report, stale_after=45, limit=3)

    def test_body_warns_instead_of_linking(self):
        self.assertIn("No release entry point is configured", self.body)

    def test_problem_is_listed(self):
        self.assertIn("Collection problems", self.body)
        self.assertIn("no release entry point found", self.body)


if __name__ == "__main__":
    unittest.main()
