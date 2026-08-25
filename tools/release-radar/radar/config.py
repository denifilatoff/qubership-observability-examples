"""Load and validate `.github/radar-config.yaml`."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import yaml


class ConfigError(ValueError):
    """Raised when the radar configuration is missing or malformed."""


@dataclass
class ComponentConfig:
    """One repository tracked inside an application."""

    repo: str
    release_workflow: Optional[str] = None
    release_method: str = "workflow"


@dataclass
class ApplicationConfig:
    """A group of components that share one tracking issue."""

    id: str
    title: str
    issue_label: str
    components: List[ComponentConfig] = field(default_factory=list)


@dataclass
class Defaults:
    """Values applied to every component unless overridden."""

    release_workflow: str = "docker-release.yaml"
    release_method: str = "workflow"
    stale_after_days: int = 45
    ignore_labels: Set[str] = field(
        default_factory=lambda: {"chore", "dependencies"}
    )
    max_ready_listed: int = 3
    verify_paths: bool = True
    internal_paths: List[str] = field(
        default_factory=lambda: [".github/", ".qubership/"]
    )


@dataclass
class Config:
    """The whole radar configuration."""

    hub_repo: str
    applications: List[ApplicationConfig]
    defaults: Defaults


def _require(mapping: Dict[str, Any], key: str, where: str) -> Any:
    """Return a required key or raise a ConfigError naming its location."""
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"{where}: missing required key `{key}`")
    return mapping[key]


def load(path: str) -> Config:
    """Read the configuration file and return a validated Config."""
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")

    defaults_raw = raw.get("defaults") or {}
    defaults = Defaults(
        release_workflow=defaults_raw.get(
            "release-workflow", Defaults.release_workflow
        ),
        release_method=str(
            defaults_raw.get("release-method", Defaults.release_method)
        ),
        stale_after_days=int(
            defaults_raw.get("stale-after-days", Defaults.stale_after_days)
        ),
        ignore_labels={
            str(label).lower()
            for label in defaults_raw.get(
                "ignore-labels", ["chore", "dependencies"]
            )
        },
        max_ready_listed=int(defaults_raw.get("max-ready-listed", 3)),
        verify_paths=bool(defaults_raw.get("verify-paths", True)),
        internal_paths=[
            str(path)
            for path in defaults_raw.get(
                "internal-paths", [".github/", ".qubership/"]
            )
        ],
    )

    hub_repo = _require(raw, "hub-repo", path)
    applications_raw = _require(raw, "applications", path)
    if not isinstance(applications_raw, list) or not applications_raw:
        raise ConfigError(f"{path}: `applications` must be a non-empty list")

    applications: List[ApplicationConfig] = []
    seen_ids: Set[str] = set()
    for index, item in enumerate(applications_raw):
        where = f"{path}: applications[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{where}: expected a mapping")
        app_id = str(_require(item, "id", where))
        if app_id in seen_ids:
            raise ConfigError(f"{where}: duplicate application id `{app_id}`")
        seen_ids.add(app_id)

        components_raw = _require(item, "components", where)
        if not isinstance(components_raw, list) or not components_raw:
            raise ConfigError(f"{where}: `components` must be a non-empty list")

        components = []
        for position, component in enumerate(components_raw):
            spot = f"{where}.components[{position}]"
            if not isinstance(component, dict):
                raise ConfigError(f"{spot}: expected a mapping")
            repo = str(_require(component, "repo", spot))
            if "/" not in repo:
                raise ConfigError(f"{spot}: `repo` must be `owner/name`")
            method = str(
                component.get("release-method", defaults.release_method)
            )
            if method not in ("workflow", "release"):
                raise ConfigError(
                    f"{spot}: `release-method` must be `workflow` or `release`"
                )
            components.append(
                ComponentConfig(
                    repo=repo,
                    release_workflow=component.get(
                        "release-workflow", defaults.release_workflow
                    ),
                    release_method=method,
                )
            )

        applications.append(
            ApplicationConfig(
                id=app_id,
                title=str(item.get("title", app_id.title())),
                issue_label=str(item.get("issue-label", f"radar/{app_id}")),
                components=components,
            )
        )

    return Config(
        hub_repo=str(hub_repo), applications=applications, defaults=defaults
    )
