"""The contract every platform adapter implements.

Keeping this surface at four calls is what makes a GitLab adapter a drop-in:
merge requests replace pull requests, pipeline status replaces check runs, and
nothing above this line has to change.
"""

from datetime import datetime
from typing import List, Optional, Protocol, Tuple

from ..model import Change, ReadyPR, Release, ReleaseAction


class Platform(Protocol):
    """Read release state and publish tracking issues for one platform."""

    def latest_release(self, repo: str) -> Optional[Release]:
        """Return the newest published release, or None when there is none."""

    def changes_since(self, repo: str, since: Optional[datetime]) -> List[Change]:
        """Return requests merged after `since`, newest first."""

    def ready_prs(self, repo: str) -> Tuple[List[ReadyPR], int]:
        """Return requests that satisfy every merge precondition, and the
        total number of open non-draft requests."""

    def changed_paths(self, repo: str, number: int) -> List[str]:
        """Return the file paths one request touches."""

    def release_action(
        self,
        repo: str,
        method: str,
        workflow: Optional[str],
        version: Optional[str],
    ) -> Optional[ReleaseAction]:
        """Return where a human starts the release, or None when unavailable."""

    def upsert_issue(self, repo: str, label: str, title: str, body: str) -> str:
        """Create or update the issue carrying `label` and return its URL."""
