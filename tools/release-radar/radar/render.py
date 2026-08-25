"""Render an application report as Markdown for a tracking issue."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from .model import (
    CATEGORY_TITLES,
    ApplicationReport,
    Bump,
    Category,
    Change,
    ComponentReport,
)
from .version import strip_prefix

CATEGORY_EMOJI = {
    Category.BREAKING: "\U0001f4a5",
    Category.FEATURE: "\U0001f4a1",
    Category.FIX: "\U0001f41e",
    Category.REFACTOR: "⚙️",
    Category.DOCS: "\U0001f4dd",
}

BUMP_NAMES = {
    Bump.MAJOR: "major",
    Bump.MINOR: "minor",
    Bump.PATCH: "patch",
    Bump.NONE: "none",
}

#: GitHub rejects issue bodies above 65536 characters.
BODY_LIMIT = 60000


def issue_title(report: ApplicationReport) -> str:
    """Return the tracking issue title for an application."""
    return f"\U0001f4e1 Release radar: {report.title}"


def _date(moment: Optional[datetime]) -> str:
    """Format a timestamp as an ISO date, or an em dash when missing."""
    return moment.strftime("%Y-%m-%d") if moment else "—"


def _age_phrase(days: Optional[int]) -> str:
    """Describe an age in days in a form that reads naturally."""
    if days is None:
        return "unknown age"
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def _plural(count: int, noun: str) -> str:
    """Return the noun in the form the count requires."""
    return noun if count == 1 else f"{noun}s"


def _change_line(change: Change) -> str:
    """Render one merged change as a bullet."""
    emoji = CATEGORY_EMOJI.get(change.category or Category.FIX, "•")
    line = f"- {emoji} [#{change.number}]({change.url}) {change.title}"
    if change.from_title:
        line += f" — ⚠️ {change.reason}"
    return line


def _grouped_changes(changes: List[Change]) -> List[str]:
    """Group changes by category, mirroring the release-drafter sections."""
    buckets: Dict[Category, List[Change]] = {}
    for change in changes:
        buckets.setdefault(change.category or Category.FIX, []).append(change)

    lines: List[str] = []
    for category in sorted(buckets, key=lambda item: item.value):
        _, heading = CATEGORY_TITLES[category]
        lines.append("")
        lines.append(f"**{CATEGORY_EMOJI[category]} {heading}**")
        lines.append("")
        lines.extend(_change_line(change) for change in buckets[category])
    return lines


def _ready_block(component: ComponentReport, limit: int) -> List[str]:
    """Render the ready-to-merge summary for one component."""
    if not component.ready:
        return ["", f"No open request is ready to merge ({component.open_count} open)."]

    ordered = sorted(component.ready, key=lambda pr: pr.idle_days, reverse=True)
    lines = [
        "",
        f"**Ready to merge: {len(ordered)} of {component.open_count} open PRs** "
        "— checks green, no conflicts, no unresolved threads, approval not required",
        "",
        "| PR | Idle | Title |",
        "|---|---|---|",
    ]
    for pull in ordered[:limit]:
        lines.append(
            f"| [#{pull.number}]({pull.url}) | {pull.idle_days} d | {pull.title} |"
        )
    remainder = ordered[limit:]
    if remainder:
        listed = ", ".join(f"[#{pull.number}]({pull.url})" for pull in remainder)
        lines.append(f"| … | | {len(remainder)} more: {listed} |")

    if (
        component.projected_version
        and component.projected_version != component.next_version
    ):
        level = BUMP_NAMES[component.projected_bump]
        lines.append("")
        lines.append(
            f"⚠️ Merging the requests above would make the next release "
            f"**`{component.projected_version}`** ({level}), not "
            f"`{component.next_version or 'the current version'}`."
        )
    return lines


def _releasable_section(
    component: ComponentReport, limit: int, stale_after: int
) -> List[str]:
    """Render a component that has changes worth releasing."""
    release = component.release
    lines = ["", f"### {component.name}", ""]

    if release is None:
        lines.append("No release found. The radar compared against the default branch.")
    else:
        tag_link = f"[`{release.tag}`]({release.url})"
        lines.append(
            f"**Release:** {tag_link} → **`{component.next_version}`** "
            f"({BUMP_NAMES[component.bump]}) · released {_date(release.published)} "
            f"({_age_phrase(release.age_days)})"
        )
        if release.from_tag_only:
            lines.append("")
            lines.append(
                "⚠️ No published release; the newest tag was used instead."
            )
        if component.stale:
            lines.append("")
            lines.append(
                f"⚠️ Last release is older than the {stale_after}-day threshold."
            )

    lines.extend(_grouped_changes(component.changes))

    deps = len(component.dependencies)
    internal = len(component.internal)
    parts = []
    if deps:
        parts.append(f"{deps} dependency {_plural(deps, 'change')}")
    if internal:
        parts.append(f"{internal} internal {_plural(internal, 'change')}")
    if parts:
        lines.append("")
        lines.append(f"_Excluded: {' and '.join(parts)}._")

    action = component.release_action
    if action is not None:
        version = strip_prefix(component.next_version)
        line = f"▶️ [{action.label}]({action.url})"
        if version:
            line += f" — version `{version}`"
        if action.hint:
            line += f" ({action.hint})"
        lines.append("")
        lines.append(line)
    else:
        lines.append("")
        lines.append("⚠️ No release entry point is configured for this component.")

    lines.extend(_ready_block(component, limit))
    return lines


def _quiet_table(components: List[ComponentReport]) -> List[str]:
    """Render components that have nothing user-facing to release."""
    lines = [
        "",
        "| Component | Released | Age | Merged since | Ready to merge |",
        "|---|---|---|---|---|",
    ]
    for component in components:
        release = component.release
        tag = f"[`{release.tag}`]({release.url})" if release else "—"
        age = f"{release.age_days} d" if release and release.age_days is not None else "—"
        skipped = len(component.dependencies) + len(component.internal)
        lines.append(
            f"| {component.name} | {tag} | {age} | {skipped} | "
            f"{len(component.ready)} of {component.open_count} |"
        )
    return lines


def _application_ready_table(report: ApplicationReport) -> List[str]:
    """Render every ready-to-merge request in the application, oldest first."""
    rows = [
        (pull, component)
        for component in report.components
        for pull in component.ready
    ]
    if not rows:
        return []
    rows.sort(key=lambda item: item[0].idle_days, reverse=True)

    lines = [
        "",
        f"## Ready to merge across {report.title}",
        "",
        f"{len(rows)} open requests are green, conflict-free, and have no unresolved "
        "threads. Sorted by time since the last update.",
        "",
        "| PR | Component | Idle | Title |",
        "|---|---|---|---|",
    ]
    for pull, component in rows:
        lines.append(
            f"| [#{pull.number}]({pull.url}) | {component.name} | "
            f"{pull.idle_days} d | {pull.title} |"
        )
    return lines


def render(report: ApplicationReport, stale_after: int, limit: int = 3) -> str:
    """Return the full Markdown body of an application tracking issue."""
    releasable = [c for c in report.components if c.releasable]
    quiet = [c for c in report.components if not c.releasable and not c.stale]
    stale = [c for c in report.components if not c.releasable and c.stale]

    stamp = (report.generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    header = f"_Updated {stamp}"
    if report.run_url:
        header += f" · [radar run]({report.run_url})"
    if report.config_url:
        header += f" · [radar-config.yaml]({report.config_url})"
    header += "_"

    lines = [
        header,
        "",
        f"**{len(releasable)} of {len(report.components)} components have "
        "releasable changes.**",
    ]

    if releasable:
        lines.append("")
        lines.append("## Ready to release")
        for component in releasable:
            lines.extend(_releasable_section(component, limit, stale_after))

    if quiet:
        lines.append("")
        lines.append("## No user-facing changes")
        lines.extend(_quiet_table(quiet))

    if stale:
        lines.append("")
        lines.append("## Stale")
        lines.append("")
        for component in stale:
            release = component.release
            tag = f"[`{release.tag}`]({release.url})" if release else "—"
            skipped = len(component.dependencies) + len(component.internal)
            lines.append(
                f"- **{component.name}** — {tag} released {_date(release.published if release else None)}, "
                f"**{release.age_days if release else '?'} days ago**, over the "
                f"{stale_after}-day threshold. {skipped} changes merged since, none user-facing."
            )

    lines.extend(_application_ready_table(report))

    errors = [
        f"- `{component.repo}`: {message}"
        for component in report.components
        for message in component.errors
    ]
    if errors:
        lines.append("")
        lines.append("## Collection problems")
        lines.append("")
        lines.extend(errors)

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "This issue is rewritten by the release radar on every run. "
        "Edits are overwritten; comments are preserved."
    )

    body = "\n".join(lines) + "\n"
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT] + "\n\n_Report truncated to fit the issue size limit._\n"
    return body
