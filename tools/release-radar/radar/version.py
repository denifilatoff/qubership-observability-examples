"""Semantic version arithmetic that preserves each repository's tag style.

`qubership-monitoring-operator` tags releases `v0.88.1` while
`qubership-version-exporter` tags them `0.6.2`. The next version the radar
prints has to match whichever style the repository already uses, or the value
cannot be pasted into the release workflow.
"""

import re
from typing import Optional

from .model import Bump

SEMVER = re.compile(
    r"^(?P<prefix>[A-Za-z]*)"
    r"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<suffix>[-+].*)?$"
)


def next_version(tag: str, bump: Bump) -> Optional[str]:
    """Return the next version for a tag, or None when it cannot be derived.

    A pre-release suffix is dropped: bumping `v1.2.0-rc.1` by a patch yields
    `v1.2.1`, not `v1.2.1-rc.1`.
    """
    if bump is Bump.NONE:
        return None
    match = SEMVER.match(tag.strip())
    if not match:
        return None

    prefix = match.group("prefix")
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))

    if bump is Bump.MAJOR:
        major, minor, patch = major + 1, 0, 0
    elif bump is Bump.MINOR:
        minor, patch = minor + 1, 0
    else:
        patch += 1

    return f"{prefix}{major}.{minor}.{patch}"


def strip_prefix(version: Optional[str]) -> Optional[str]:
    """Return a version without its tag prefix, for workflow input values."""
    if version is None:
        return None
    match = SEMVER.match(version.strip())
    if not match:
        return version
    return version.strip()[len(match.group("prefix")):]
