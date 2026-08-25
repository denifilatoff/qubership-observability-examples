"""Decide what a merged change means for the next release.

The org labels pull requests unevenly: `chore(deps)` requests carry a `bug`
label, `fix(ci)` requests are labeled `enhancement`, and some requests carry no
label at all. A label-first classifier therefore recommends releases that hold
nothing a user would notice. The rules below invert that order for exclusions:
a `chore`, `ci`, or `build` title wins over any label, and only what survives
that filter is classified by label.
"""

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from .model import Bump, Category, Change, Kind

CONVENTIONAL = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<subject>.+)$"
)

#: Title types that never justify a release, whatever the labels say.
EXCLUDED_TYPES = frozenset({"chore", "build", "ci", "test", "tests", "style"})

#: Scopes that mark a change as internal, whatever its type.
INTERNAL_SCOPES = frozenset({"ci", "build", "test", "tests", "e2e", "lint"})

#: Scopes that mark a change as a dependency update.
DEPENDENCY_SCOPES = frozenset({"deps", "dependencies"})

LABEL_BUMPS = {
    "breaking-change": Bump.MAJOR,
    "breaking": Bump.MAJOR,
    "major": Bump.MAJOR,
    "enhancement": Bump.MINOR,
    "feature": Bump.MINOR,
    "minor": Bump.MINOR,
    "bug": Bump.PATCH,
    "fix": Bump.PATCH,
    "bugfix": Bump.PATCH,
    "refactor": Bump.PATCH,
    "documentation": Bump.PATCH,
    "docs": Bump.PATCH,
    "patch": Bump.PATCH,
}

LABEL_CATEGORIES = {
    "breaking-change": Category.BREAKING,
    "breaking": Category.BREAKING,
    "major": Category.BREAKING,
    "enhancement": Category.FEATURE,
    "feature": Category.FEATURE,
    "minor": Category.FEATURE,
    "bug": Category.FIX,
    "fix": Category.FIX,
    "bugfix": Category.FIX,
    "patch": Category.FIX,
    "refactor": Category.REFACTOR,
    "documentation": Category.DOCS,
    "docs": Category.DOCS,
}

TYPE_RULES = {
    "feat": (Bump.MINOR, Category.FEATURE),
    "feature": (Bump.MINOR, Category.FEATURE),
    "fix": (Bump.PATCH, Category.FIX),
    "perf": (Bump.PATCH, Category.FIX),
    "revert": (Bump.PATCH, Category.FIX),
    "refactor": (Bump.PATCH, Category.REFACTOR),
    "docs": (Bump.PATCH, Category.DOCS),
    "doc": (Bump.PATCH, Category.DOCS),
}

DEFAULT_IGNORE_LABELS = frozenset({"dependencies", "deps", "chore"})


def _parse_title(title: str) -> Tuple[Optional[str], Optional[str], bool]:
    """Split a conventional-commit title into type, scope, and breaking flag."""
    match = CONVENTIONAL.match(title.strip())
    if not match:
        return None, None, False
    scope = match.group("scope")
    return (
        match.group("type").lower(),
        scope.lower().strip() if scope else None,
        bool(match.group("bang")),
    )


def _strongest_label(labels: Iterable[str]) -> Tuple[Bump, Optional[Category]]:
    """Return the highest bump the labels justify, with its category."""
    bump = Bump.NONE
    category: Optional[Category] = None
    for label in labels:
        key = label.lower()
        candidate = LABEL_BUMPS.get(key)
        if candidate is None:
            continue
        if candidate > bump:
            bump = candidate
            category = LABEL_CATEGORIES.get(key)
        elif candidate == bump and category is None:
            category = LABEL_CATEGORIES.get(key)
    return bump, category


def classify(change: Change, ignore_labels: Optional[Set[str]] = None) -> Change:
    """Assign kind, bump, and category to one change, in place.

    Rule order matters. Exclusions are decided by the title first, because the
    title reflects what the author did and the label often reflects what a bot
    guessed.
    """
    ignored = set(ignore_labels or DEFAULT_IGNORE_LABELS)
    labels = {label.lower() for label in change.labels}
    ctype, scope, breaking = _parse_title(change.title)

    if scope in DEPENDENCY_SCOPES:
        change.kind = Kind.DEPENDENCY
        change.reason = f"dependency scope `{scope}`"
        return change

    if ctype in EXCLUDED_TYPES:
        change.kind = Kind.INTERNAL
        change.reason = f"`{ctype}` title overrides labels"
        return change

    if scope in INTERNAL_SCOPES:
        change.kind = Kind.INTERNAL
        change.reason = f"internal scope `{scope}`"
        return change

    if labels & ignored:
        change.kind = Kind.DEPENDENCY
        change.reason = "ignored label"
        return change

    change.kind = Kind.RELEASABLE

    if breaking or "BREAKING CHANGE" in change.title:
        change.bump = Bump.MAJOR
        change.category = Category.BREAKING
        return change

    label_bump, label_category = _strongest_label(labels)
    if label_bump is not Bump.NONE:
        change.bump = label_bump
        change.category = label_category or Category.FIX
        return change

    rule = TYPE_RULES.get(ctype or "")
    if rule is not None:
        change.bump, change.category = rule
        change.from_title = True
        change.reason = f"classified from `{ctype}:` title, no matching label"
        return change

    change.bump = Bump.PATCH
    change.category = Category.FIX
    change.from_title = True
    change.reason = "no label and no conventional-commit prefix"
    return change


def classify_all(
    changes: Sequence[Change], ignore_labels: Optional[Set[str]] = None
) -> List[Change]:
    """Classify every change and return them as a list."""
    return [classify(change, ignore_labels) for change in changes]


def is_internal_path_set(paths: Sequence[str], internal_prefixes: Sequence[str]) -> bool:
    """Return True when every changed path is repository plumbing."""
    return all(
        any(path.startswith(prefix) for prefix in internal_prefixes)
        for path in paths
    )


def combined_bump(changes: Iterable[Change]) -> Bump:
    """Return the strongest bump among releasable changes."""
    levels = [c.bump for c in changes if c.kind is Kind.RELEASABLE]
    return max(levels) if levels else Bump.NONE
