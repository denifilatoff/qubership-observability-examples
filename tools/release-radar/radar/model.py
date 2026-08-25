"""Platform-neutral data model shared by adapters and the renderer."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import List, Optional


class Bump(IntEnum):
    """Semantic version bump level, ordered so max() picks the strongest."""

    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


class Kind(IntEnum):
    """What a merged change means for a release."""

    RELEASABLE = 0
    INTERNAL = 1
    DEPENDENCY = 2


class Category(IntEnum):
    """Release-note grouping, mirroring release-drafter categories."""

    BREAKING = 0
    FEATURE = 1
    FIX = 2
    REFACTOR = 3
    DOCS = 4


CATEGORY_TITLES = {
    Category.BREAKING: ("breaking", "Breaking changes"),
    Category.FEATURE: ("feature", "New features"),
    Category.FIX: ("fix", "Bug fixes"),
    Category.REFACTOR: ("refactor", "Technical debt"),
    Category.DOCS: ("docs", "Documentation"),
}


@dataclass
class Change:
    """A merged pull or merge request considered for the next release."""

    number: int
    title: str
    url: str
    author: str
    labels: List[str] = field(default_factory=list)
    bump: Bump = Bump.NONE
    kind: Kind = Kind.RELEASABLE
    category: Optional[Category] = None
    from_title: bool = False
    reason: str = ""


@dataclass
class ReadyPR:
    """An open request that satisfies every merge precondition."""

    number: int
    title: str
    url: str
    repo: str
    idle_days: int
    labels: List[str] = field(default_factory=list)
    bump: Bump = Bump.NONE


@dataclass
class Release:
    """The most recent published release of a component."""

    tag: str
    url: str
    published: Optional[datetime]
    age_days: Optional[int]
    from_tag_only: bool = False


@dataclass
class ReleaseAction:
    """How a human starts the release, and where to click."""

    label: str
    url: str
    hint: str = ""


@dataclass
class ComponentReport:
    """Everything the radar knows about a single component."""

    repo: str
    release: Optional[Release] = None
    next_version: Optional[str] = None
    bump: Bump = Bump.NONE
    changes: List[Change] = field(default_factory=list)
    internal: List[Change] = field(default_factory=list)
    dependencies: List[Change] = field(default_factory=list)
    ready: List[ReadyPR] = field(default_factory=list)
    open_count: int = 0
    release_action: Optional[ReleaseAction] = None
    projected_version: Optional[str] = None
    projected_bump: Bump = Bump.NONE
    stale: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Return the short repository name without its owner prefix."""
        return self.repo.split("/")[-1]

    @property
    def releasable(self) -> bool:
        """Return True when merged changes justify a new release."""
        return bool(self.changes)


@dataclass
class ApplicationReport:
    """One application: the unit that gets its own tracking issue."""

    id: str
    title: str
    issue_label: str
    components: List[ComponentReport] = field(default_factory=list)
    generated_at: Optional[datetime] = None
    run_url: Optional[str] = None
    config_url: Optional[str] = None
