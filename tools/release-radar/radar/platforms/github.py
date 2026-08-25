"""GitHub adapter built on the REST and GraphQL APIs.

Mergeability needs GraphQL: the Search API cannot express "no merge conflict"
or "no unresolved review thread". GitHub also computes the merge commit
lazily, so a first query returns `mergeable: UNKNOWN` for most requests and the
query itself schedules the computation. The adapter therefore re-queries once
the values have settled.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..model import Change, ReadyPR, Release, ReleaseAction

API_ROOT = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"
USER_AGENT = "qubership-release-radar"

OPEN_PR_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 50, after: $cursor,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        url
        isDraft
        mergeable
        updatedAt
        labels(first: 20) { nodes { name } }
        reviewThreads(first: 50) { nodes { isResolved } }
        commits(last: 1) {
          nodes { commit { statusCheckRollup { state } } }
        }
      }
    }
  }
}
"""


class GitHubError(RuntimeError):
    """Raised when the GitHub API cannot satisfy a request."""


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp returned by GitHub."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHubClient:
    """Minimal GitHub client with retry handling and no external dependency."""

    def __init__(
        self,
        token: str,
        api_root: str = API_ROOT,
        graphql_url: str = GRAPHQL_URL,
        settle_seconds: float = 4.0,
    ) -> None:
        if not token:
            raise GitHubError("a GitHub token is required")
        self._token = token
        self._api_root = api_root.rstrip("/")
        self._graphql_url = graphql_url
        self.settle_seconds = settle_seconds

    def _send(
        self, method: str, url: str, payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, Any]:
        """Send one request and return its status code and decoded body."""
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", USER_AGENT)
        if data is not None:
            request.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            try:
                decoded = json.loads(body) if body else None
            except json.JSONDecodeError:
                decoded = {"message": body}
            return error.code, decoded

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        attempts: int = 4,
    ) -> Any:
        """Call a REST endpoint, retrying on rate limits and 5xx responses."""
        url = path if path.startswith("http") else f"{self._api_root}{path}"
        delay = 2.0
        for attempt in range(attempts):
            status, body = self._send(method, url, payload)
            if 200 <= status < 300:
                return body
            if status == 404:
                return None
            retryable = status in (403, 429) or status >= 500
            if not retryable or attempt == attempts - 1:
                message = ""
                if isinstance(body, dict):
                    message = str(body.get("message", ""))
                raise GitHubError(f"{method} {url} failed: {status} {message}")
            time.sleep(delay)
            delay *= 2
        raise GitHubError(f"{method} {url} exhausted retries")

    def graphql(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Run a GraphQL query and return its `data` payload."""
        delay = 2.0
        for attempt in range(4):
            status, body = self._send(
                "POST", self._graphql_url, {"query": query, "variables": variables}
            )
            if 200 <= status < 300 and isinstance(body, dict):
                if body.get("errors"):
                    raise GitHubError(f"GraphQL error: {body['errors']}")
                return body.get("data") or {}
            if attempt == 3:
                raise GitHubError(f"GraphQL request failed: {status} {body}")
            time.sleep(delay)
            delay *= 2
        raise GitHubError("GraphQL request exhausted retries")


class GitHubPlatform:
    """Platform adapter reading component state from GitHub."""

    def __init__(self, client: GitHubClient, now: Optional[datetime] = None) -> None:
        self._client = client
        self._now = now or datetime.now(timezone.utc)

    def latest_release(self, repo: str) -> Optional[Release]:
        """Return the newest release, falling back to the newest tag."""
        data = self._client.request("GET", f"/repos/{repo}/releases/latest")
        if data:
            published = _parse_time(data.get("published_at"))
            return Release(
                tag=data["tag_name"],
                url=data.get("html_url", ""),
                published=published,
                age_days=self._age(published),
            )

        tags = self._client.request("GET", f"/repos/{repo}/tags?per_page=1")
        if not tags:
            return None
        tag = tags[0]
        commit = self._client.request(
            "GET", f"/repos/{repo}/commits/{tag['commit']['sha']}"
        )
        published = None
        if commit:
            published = _parse_time(
                commit.get("commit", {}).get("committer", {}).get("date")
            )
        return Release(
            tag=tag["name"],
            url=f"https://github.com/{repo}/releases/tag/{tag['name']}",
            published=published,
            age_days=self._age(published),
            from_tag_only=True,
        )

    def changes_since(self, repo: str, since: Optional[datetime]) -> List[Change]:
        """Return pull requests merged after `since`, newest first."""
        query = f"repo:{repo} is:pr is:merged"
        if since is not None:
            stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            query += f" merged:>{stamp}"

        changes: List[Change] = []
        for page in range(1, 6):
            params = urllib.parse.urlencode(
                {"q": query, "per_page": 100, "page": page, "sort": "updated"}
            )
            payload = self._client.request("GET", f"/search/issues?{params}")
            items = (payload or {}).get("items", [])
            for item in items:
                changes.append(
                    Change(
                        number=item["number"],
                        title=item["title"],
                        url=item["html_url"],
                        author=(item.get("user") or {}).get("login", "unknown"),
                        labels=[label["name"] for label in item.get("labels", [])],
                    )
                )
            if len(items) < 100:
                break
        return changes

    def ready_prs(self, repo: str) -> Tuple[List[ReadyPR], int]:
        """Return open requests that are green, conflict-free, and unblocked.

        Approval is deliberately not checked. Requiring it would hide the
        requests that most need attention: the ones waiting for a review.
        """
        nodes = self._open_pull_requests(repo)
        unknown = [n for n in nodes if n.get("mergeable") == "UNKNOWN"]
        if unknown:
            time.sleep(self._client.settle_seconds)
            nodes = self._open_pull_requests(repo)

        ready: List[ReadyPR] = []
        open_count = 0
        for node in nodes:
            if node.get("isDraft"):
                continue
            open_count += 1
            rollup = (node.get("commits") or {}).get("nodes") or [{}]
            state = ((rollup[0].get("commit") or {}).get("statusCheckRollup") or {}).get(
                "state"
            )
            threads = (node.get("reviewThreads") or {}).get("nodes") or []
            unresolved = [t for t in threads if not t.get("isResolved")]
            if node.get("mergeable") != "MERGEABLE" or state != "SUCCESS":
                continue
            if unresolved:
                continue
            updated = _parse_time(node.get("updatedAt"))
            ready.append(
                ReadyPR(
                    number=node["number"],
                    title=node["title"],
                    url=node["url"],
                    repo=repo,
                    idle_days=self._age(updated) or 0,
                    labels=[
                        label["name"]
                        for label in (node.get("labels") or {}).get("nodes") or []
                    ],
                )
            )
        return ready, open_count

    def _open_pull_requests(self, repo: str) -> List[Dict[str, Any]]:
        """Page through every open pull request of a repository."""
        owner, name = repo.split("/", 1)
        nodes: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(10):
            data = self._client.graphql(
                OPEN_PR_QUERY, {"owner": owner, "name": name, "cursor": cursor}
            )
            repository = data.get("repository") or {}
            block = repository.get("pullRequests") or {}
            nodes.extend(block.get("nodes") or [])
            page = block.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")
        return nodes

    def changed_paths(self, repo: str, number: int) -> List[str]:
        """Return every file path a pull request touches."""
        paths: List[str] = []
        for page in range(1, 4):
            payload = self._client.request(
                "GET", f"/repos/{repo}/pulls/{number}/files?per_page=100&page={page}"
            )
            if not payload:
                break
            paths.extend(item["filename"] for item in payload)
            if len(payload) < 100:
                break
        return paths

    def release_action(
        self,
        repo: str,
        method: str,
        workflow: Optional[str],
        version: Optional[str],
    ) -> Optional[ReleaseAction]:
        """Return the link that starts a release for this component.

        Components differ in how they ship. Some dispatch a release workflow;
        others build on `release: created`, so the action is creating the
        release itself — and that URL can be prefilled with the computed
        version.
        """
        if method == "release":
            if not version:
                return None
            params = urllib.parse.urlencode({"tag": version, "title": version})
            return ReleaseAction(
                label="Draft the release",
                url=f"https://github.com/{repo}/releases/new?{params}",
                hint="the build runs on `release: created`",
            )

        if not workflow:
            return None
        encoded = urllib.parse.quote(workflow, safe="")
        found = self._client.request(
            "GET", f"/repos/{repo}/actions/workflows/{encoded}"
        )
        if not found:
            return None
        return ReleaseAction(
            label=f"Run {workflow}",
            url=f"https://github.com/{repo}/actions/workflows/{workflow}",
            hint="",
        )

    def upsert_issue(self, repo: str, label: str, title: str, body: str) -> str:
        """Create the tracking issue or rewrite the existing one."""
        self._ensure_label(repo, label)
        params = urllib.parse.urlencode(
            {"labels": label, "state": "all", "per_page": 10}
        )
        existing = self._client.request("GET", f"/repos/{repo}/issues?{params}") or []
        issues = [item for item in existing if "pull_request" not in item]

        if issues:
            issue = sorted(issues, key=lambda item: item["number"])[0]
            updated = self._client.request(
                "PATCH",
                f"/repos/{repo}/issues/{issue['number']}",
                {"title": title, "body": body, "state": "open"},
            )
            return (updated or issue).get("html_url", "")

        created = self._client.request(
            "POST",
            f"/repos/{repo}/issues",
            {"title": title, "body": body, "labels": [label]},
        )
        return (created or {}).get("html_url", "")

    def _ensure_label(self, repo: str, label: str) -> None:
        """Create the tracking label when the repository lacks it."""
        encoded = urllib.parse.quote(label, safe="")
        if self._client.request("GET", f"/repos/{repo}/labels/{encoded}"):
            return
        self._client.request(
            "POST",
            f"/repos/{repo}/labels",
            {
                "name": label,
                "color": "1d76db",
                "description": "Release radar tracking issue",
            },
        )

    def _age(self, moment: Optional[datetime]) -> Optional[int]:
        """Return whole days between `moment` and the run timestamp."""
        if moment is None:
            return None
        return max((self._now - moment).days, 0)
