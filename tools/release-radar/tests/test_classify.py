"""Classifier tests built from real Netcracker pull requests."""

import unittest

from radar.classify import classify
from radar.model import Bump, Category, Change, Kind


def make(number, title, labels=None):
    """Build a Change the way the GitHub adapter would."""
    return Change(
        number=number,
        title=title,
        url=f"https://example.invalid/{number}",
        author="someone",
        labels=labels or [],
    )


class TitleBeatsLabel(unittest.TestCase):
    """A `chore`, `ci`, or `build` title overrides a misleading label."""

    def test_chore_deps_labeled_bug_is_a_dependency(self):
        # qubership-prometheus-adapter-operator#207
        change = classify(
            make(207, "chore(deps): update Go builder images to 1.26.6-alpine3.24", ["bug"])
        )
        self.assertIs(change.kind, Kind.DEPENDENCY)

    def test_chore_deps_labeled_feature_is_not_a_minor_release(self):
        # qubership-grafana-reporter#126, labeled bug AND enhancement
        change = classify(
            make(126, "chore(deps): use shared Renovate config", ["bug", "enhancement"])
        )
        self.assertIs(change.kind, Kind.DEPENDENCY)
        self.assertIs(change.bump, Bump.NONE)

    def test_fix_build_labeled_bug_is_internal(self):
        # qubership-prometheus-adapter-operator#211
        change = classify(make(211, "fix(build): pin Go builder Alpine version", ["bug"]))
        self.assertIs(change.kind, Kind.INTERNAL)

    def test_fix_ci_labeled_bug_is_internal(self):
        # qubership-monitoring-operator#482
        change = classify(
            make(482, "fix(ci): ignore expected Renovate timestamp notices", ["bug"])
        )
        self.assertIs(change.kind, Kind.INTERNAL)


class ReleasableChanges(unittest.TestCase):
    """Changes a user would notice are classified by label, then by title."""

    def test_labeled_bug_fix_is_a_patch(self):
        # qubership-monitoring-operator#506
        change = classify(make(506, "fix: allow disabling Grafana", ["bug"]))
        self.assertIs(change.kind, Kind.RELEASABLE)
        self.assertIs(change.bump, Bump.PATCH)
        self.assertIs(change.category, Category.FIX)
        self.assertFalse(change.from_title)

    def test_unlabeled_fix_falls_back_to_the_title(self):
        # qubership-monitoring-operator#494
        change = classify(make(494, "fix: pin operator and integration-tests images"))
        self.assertIs(change.kind, Kind.RELEASABLE)
        self.assertIs(change.bump, Bump.PATCH)
        self.assertTrue(change.from_title)

    def test_feature_label_wins_over_a_bug_label(self):
        # qubership-monitoring-operator#478
        change = classify(
            make(478, "feat: add opt-in leaderElect", ["bug", "enhancement"])
        )
        self.assertIs(change.bump, Bump.MINOR)
        self.assertIs(change.category, Category.FEATURE)

    def test_exclamation_marks_a_breaking_change(self):
        change = classify(make(1, "feat!: drop Kubernetes 1.27 support"))
        self.assertIs(change.bump, Bump.MAJOR)
        self.assertIs(change.category, Category.BREAKING)

    def test_unparsable_title_without_labels_is_flagged(self):
        change = classify(make(2, "Update the operator"))
        self.assertIs(change.kind, Kind.RELEASABLE)
        self.assertIs(change.bump, Bump.PATCH)
        self.assertTrue(change.from_title)
        self.assertIn("no conventional-commit prefix", change.reason)


if __name__ == "__main__":
    unittest.main()
