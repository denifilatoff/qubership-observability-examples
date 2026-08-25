"""Turn configuration plus a platform adapter into application reports."""

from datetime import datetime, timezone
from typing import List, Optional

from .classify import classify, classify_all, combined_bump, is_internal_path_set
from .config import ApplicationConfig, ComponentConfig, Defaults
from .model import (
    ApplicationReport,
    Bump,
    Change,
    ComponentReport,
    Kind,
)
from .platforms.base import Platform
from .version import next_version


def _projected(
    component: ComponentReport, defaults: Defaults
) -> tuple[Optional[str], Bump]:
    """Return the version reached if every ready request were merged first."""
    if component.release is None or not component.ready:
        return None, Bump.NONE

    levels = [change.bump for change in component.changes]
    for pull in component.ready:
        probe = classify(
            Change(
                number=pull.number,
                title=pull.title,
                url=pull.url,
                author="",
                labels=list(pull.labels),
            ),
            defaults.ignore_labels,
        )
        pull.bump = probe.bump if probe.kind is Kind.RELEASABLE else Bump.NONE
        if probe.kind is Kind.RELEASABLE:
            levels.append(probe.bump)

    if not levels:
        return None, Bump.NONE
    bump = max(levels)
    return next_version(component.release.tag, bump), bump


#: Path verification costs one request per candidate; keep it bounded.
MAX_PATH_CHECKS = 30


def _verify_paths(
    platform: Platform, repo: str, report: ComponentReport, defaults: Defaults
) -> None:
    """Demote changes that touch only CI or repository plumbing.

    A `feat:` title on a request that edits nothing but `.github/` is a CI
    change, whatever the title claims. This catches what neither the label nor
    the title can: `qubership-grafana-reporter#78`, titled
    `feat: Add security scan workflow`, touches only `.github/workflows/` and
    `.qubership/`.
    """
    kept: List[Change] = []
    for index, change in enumerate(report.changes):
        if index >= MAX_PATH_CHECKS:
            kept.append(change)
            continue
        try:
            paths = platform.changed_paths(repo, change.number)
        except Exception as error:  # noqa: BLE001
            report.errors.append(
                f"could not read files of #{change.number}: {error}"
            )
            kept.append(change)
            continue
        if paths and is_internal_path_set(paths, defaults.internal_paths):
            change.kind = Kind.INTERNAL
            change.bump = Bump.NONE
            change.reason = "touches only CI and repository configuration"
            report.internal.append(change)
        else:
            kept.append(change)
    report.changes = kept


def collect_component(
    platform: Platform, spec: ComponentConfig, defaults: Defaults
) -> ComponentReport:
    """Gather release state, merged changes, and ready requests for one repo."""
    report = ComponentReport(repo=spec.repo)
    try:
        report.release = platform.latest_release(spec.repo)
    except Exception as error:  # noqa: BLE001 - one bad repo must not stop the run
        report.errors.append(f"could not read the latest release: {error}")
        return report

    since = report.release.published if report.release else None
    try:
        raw = platform.changes_since(spec.repo, since)
    except Exception as error:  # noqa: BLE001
        report.errors.append(f"could not list merged requests: {error}")
        raw = []

    for change in classify_all(raw, defaults.ignore_labels):
        if change.kind is Kind.RELEASABLE:
            report.changes.append(change)
        elif change.kind is Kind.DEPENDENCY:
            report.dependencies.append(change)
        else:
            report.internal.append(change)

    if defaults.verify_paths and report.changes:
        _verify_paths(platform, spec.repo, report, defaults)

    report.bump = combined_bump(report.changes)
    if report.release is not None:
        report.next_version = next_version(report.release.tag, report.bump)
        if report.bump is not Bump.NONE and report.next_version is None:
            report.errors.append(
                f"tag `{report.release.tag}` is not semantic; no version proposed"
            )
        if report.release.age_days is not None:
            report.stale = report.release.age_days > defaults.stale_after_days

    try:
        report.ready, report.open_count = platform.ready_prs(spec.repo)
    except Exception as error:  # noqa: BLE001
        report.errors.append(f"could not read open requests: {error}")

    report.projected_version, report.projected_bump = _projected(report, defaults)

    workflow = spec.release_workflow or defaults.release_workflow
    try:
        report.release_action = platform.release_action(
            spec.repo, spec.release_method, workflow, report.next_version
        )
    except Exception as error:  # noqa: BLE001
        report.errors.append(f"could not resolve the release action: {error}")
    if report.release_action is None and report.releasable:
        report.errors.append(
            f"no release entry point found (method `{spec.release_method}`, "
            f"workflow `{workflow}`)"
        )
    return report


def collect_application(
    platform: Platform,
    spec: ApplicationConfig,
    defaults: Defaults,
    now: Optional[datetime] = None,
    run_url: Optional[str] = None,
    config_url: Optional[str] = None,
) -> ApplicationReport:
    """Collect every component of one application."""
    components: List[ComponentReport] = [
        collect_component(platform, component, defaults)
        for component in spec.components
    ]
    return ApplicationReport(
        id=spec.id,
        title=spec.title,
        issue_label=spec.issue_label,
        components=components,
        generated_at=now or datetime.now(timezone.utc),
        run_url=run_url,
        config_url=config_url,
    )
