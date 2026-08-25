# Release radar

The radar reports what is worth releasing across the qubership observability components, and what is waiting to be
merged. It runs on a schedule, keeps one tracking issue per application in this repository, and rewrites that issue on
every run.

Components are public, so the radar reads them with the built-in `GITHUB_TOKEN`. It needs no personal access token and
no write permission outside this repository.

## What one issue contains

For every component of an application:

- the latest release, its age, and the version the merged changes justify next;
- the merged changes that a user would notice, grouped the way release-drafter groups them;
- open requests that are ready to merge, and how long each has been idle;
- a link that starts the release, prefilled with the computed version.

An application with nothing to release still gets an issue: it reports the quiet components and any stale one.

## Running it locally

```bash
export GITHUB_TOKEN=$(gh auth token)
export PYTHONPATH=tools/release-radar
pip install -r tools/release-radar/requirements.txt

# Render every application to stdout without touching any issue.
python -m radar --config .github/radar-config.yaml --dry-run

# Render one application and keep the Markdown on disk.
python -m radar --config .github/radar-config.yaml --application monitoring --dry-run --output-dir /tmp/radar

# Create or update the tracking issues.
python -m radar --config .github/radar-config.yaml --publish
```

Without `--publish`, the radar never writes. The workflow publishes; a local run defaults to a dry run.

## Configuration

Applications and their components live in [.github/radar-config.yaml](../../.github/radar-config.yaml).

```yaml
hub-repo: Netcracker/qubership-observability-examples

defaults:
  release-workflow: docker-release.yaml   # dispatched when release-method is `workflow`
  release-method: workflow                # `workflow` or `release`
  stale-after-days: 45                    # older than this is reported as stale
  ignore-labels: [chore, dependencies]    # labels that never justify a release
  max-ready-listed: 3                     # ready requests listed per component before the rest collapse
  verify-paths: true                      # demote changes that touch only CI configuration
  internal-paths: ['.github/', '.qubership/']

applications:
  - id: monitoring
    title: Monitoring
    issue-label: radar/monitoring
    components:
      - repo: Netcracker/qubership-monitoring-operator
        release-workflow: docker-release.yaml
      - repo: Netcracker/qubership-version-exporter
        release-method: release
```

Components ship in one of two ways, and the radar links to whichever applies:

<!-- markdownlint-disable line-length -->
| `release-method` | What the component does                                | Where the issue links                                   |
| ---------------- | ------------------------------------------------------ | ------------------------------------------------------- |
| `workflow`       | a `workflow_dispatch` release workflow builds and tags | the workflow's run page                                 |
| `release`        | `build.yml` triggers on `release: created`             | a new-release form, prefilled with the computed version |
<!-- markdownlint-enable line-length -->

When a `workflow` component has no such workflow, the radar says so instead of printing a dead link.

## How a change is classified

Labels alone misclassify this org's requests. `chore(deps)` requests carry `bug` labels, `fix(ci)` requests carry
`enhancement`, and some requests carry no label at all. The radar therefore decides exclusions from the title first,
then classifies whatever survives:

1. A `deps` scope is a dependency update.
2. A `chore`, `build`, `ci`, `test`, or `style` title is internal, whatever its labels say.
3. A `ci`, `build`, `test`, or `lint` scope is internal.
4. An ignored label is a dependency update.
5. Otherwise labels decide the bump: `breaking-change` is major, `enhancement` is minor, `bug` is a patch.
6. With no usable label, the conventional-commit type decides, and the entry is flagged in the issue.
7. Finally, a change whose files all sit under `internal-paths` is demoted to internal.

Step 7 catches what nothing else can. `qubership-grafana-reporter#78`, titled `feat: Add security scan workflow`, would
otherwise propose a minor release for a change that touches only `.github/` and `.qubership/`.

## What counts as ready to merge

A request is ready when its checks pass, it has no merge conflict, it has no unresolved review thread, and it is not a
draft. Approval is deliberately not required: approval is usually the missing step, so requiring it would hide the
requests that most need a reviewer.

Mergeability comes from GraphQL, because the search API cannot express "no conflict" or "no unresolved thread". GitHub
computes the merge commit lazily and answers `UNKNOWN` on first ask, so the radar queries, waits, and asks again.

## Layout

```text
tools/release-radar/
  radar/
    __main__.py        command-line entry point
    collect.py         config plus adapter to reports
    classify.py        title and label rules
    version.py         semantic version arithmetic
    render.py          Markdown issue body
    model.py           platform-neutral data model
    platforms/
      base.py          the four-call adapter contract
      github.py        REST and GraphQL adapter
  tests/               unit tests over real fixtures
```

`platforms/base.py` is what keeps a GitLab adapter a drop-in: merge requests replace pull requests, pipeline status
replaces check runs, and nothing above that line changes.

## Tests

```bash
PYTHONPATH=tools/release-radar python -m unittest discover -s tools/release-radar/tests -t tools/release-radar
```

The fixtures are real requests from the org, including the ones that defeat a label-first classifier.

## Known limits

- A request merged into a release branch rather than the default branch is not counted.
- A `feat:` request that touches product files but is really internal still counts. Scopes fix this at the source.
- The proposed version assumes semantic versioning. A component with a non-semantic tag is reported without a proposal.
