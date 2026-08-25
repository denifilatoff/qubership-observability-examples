"""Command-line entry point for the release radar.

Examples
--------
Preview every application without touching any issue::

    GITHUB_TOKEN=... python -m radar --config .github/radar-config.yaml --dry-run

Publish one application::

    GITHUB_TOKEN=... python -m radar --config .github/radar-config.yaml \
        --application monitoring --publish
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from .collect import collect_application
from .config import Config, ConfigError, load
from .model import ApplicationReport
from .platforms.github import GitHubClient, GitHubError, GitHubPlatform
from .render import issue_title, render


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="radar", description="Report release readiness across repositories."
    )
    parser.add_argument(
        "--config",
        default=".github/radar-config.yaml",
        help="path to the radar configuration file",
    )
    parser.add_argument(
        "--application",
        action="append",
        dest="applications",
        help="limit the run to this application id; repeatable",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="create or update the tracking issues",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="render the issues and print them without publishing",
    )
    parser.add_argument(
        "--output-dir",
        help="also write each rendered issue body to this directory",
    )
    return parser.parse_args(argv)


def _run_url() -> Optional[str]:
    """Build a link back to the workflow run, when running in Actions."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not repo or not run_id:
        return None
    return f"{server}/{repo}/actions/runs/{run_id}"


def _config_url(config: Config, path: str) -> str:
    """Build a link to the configuration file used for this run."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"{server}/{config.hub_repo}/blob/{branch}/{path}"


def _write_summary(lines: List[str]) -> None:
    """Append a short run summary to the Actions job summary, if available."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _summarize(report: ApplicationReport) -> str:
    """Return a one-line summary of an application report."""
    releasable = sum(1 for c in report.components if c.releasable)
    ready = sum(len(c.ready) for c in report.components)
    return (
        f"| {report.title} | {releasable} of {len(report.components)} | {ready} |"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the radar and return a process exit code."""
    args = _parse_args(argv)

    if not args.publish and not args.dry_run:
        args.dry_run = True

    try:
        config = load(args.config)
    except (ConfigError, OSError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 2

    try:
        platform = GitHubPlatform(GitHubClient(token), now=datetime.now(timezone.utc))
    except GitHubError as error:
        print(f"github error: {error}", file=sys.stderr)
        return 2

    selected = [
        app
        for app in config.applications
        if not args.applications or app.id in args.applications
    ]
    if not selected:
        print("no application matched the --application filter", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    summary = ["| Application | Releasable | Ready to merge |", "|---|---|---|"]
    failures = 0

    for spec in selected:
        report = collect_application(
            platform,
            spec,
            config.defaults,
            run_url=_run_url(),
            config_url=_config_url(config, args.config),
        )
        title = issue_title(report)
        body = render(
            report, config.defaults.stale_after_days, config.defaults.max_ready_listed
        )
        summary.append(_summarize(report))

        if output_dir:
            (output_dir / f"{spec.id}.md").write_text(body, encoding="utf-8")

        if args.dry_run:
            print(f"===== {title} [{spec.issue_label}] =====")
            print(body)
            continue

        try:
            url = platform.upsert_issue(
                config.hub_repo, spec.issue_label, title, body
            )
            print(f"{spec.id}: {url}")
        except GitHubError as error:
            failures += 1
            print(f"{spec.id}: publishing failed: {error}", file=sys.stderr)

    _write_summary(summary)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
