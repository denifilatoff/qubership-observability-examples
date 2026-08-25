"""Version arithmetic tests, including the org's mixed tag styles."""

import unittest

from radar.model import Bump
from radar.version import next_version, strip_prefix


class NextVersion(unittest.TestCase):
    """The proposed version keeps whatever style the repository uses."""

    def test_prefixed_tag_keeps_its_prefix(self):
        self.assertEqual(next_version("v0.88.1", Bump.PATCH), "v0.88.2")

    def test_bare_tag_stays_bare(self):
        self.assertEqual(next_version("0.6.2", Bump.MINOR), "0.7.0")

    def test_major_resets_minor_and_patch(self):
        self.assertEqual(next_version("2.10.2", Bump.MAJOR), "3.0.0")

    def test_prerelease_suffix_is_dropped(self):
        self.assertEqual(next_version("v1.2.0-rc.1", Bump.PATCH), "v1.2.1")

    def test_no_bump_proposes_nothing(self):
        self.assertIsNone(next_version("v0.88.1", Bump.NONE))

    def test_non_semantic_tag_proposes_nothing(self):
        self.assertIsNone(next_version("release-2026-08", Bump.PATCH))


class StripPrefix(unittest.TestCase):
    """Workflow inputs take the bare number."""

    def test_prefix_removed(self):
        self.assertEqual(strip_prefix("v0.88.2"), "0.88.2")

    def test_bare_version_unchanged(self):
        self.assertEqual(strip_prefix("0.88.2"), "0.88.2")

    def test_none_passes_through(self):
        self.assertIsNone(strip_prefix(None))


if __name__ == "__main__":
    unittest.main()
