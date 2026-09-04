# Renovate actions

These composite actions run inside a prepared GitHub Actions job. They do not install tools, check out a repository,
or configure a container. Use them together with the caller workflow below.

## Runtime contract

| Action | Required tools | Caller environment | Result |
| --- | --- | --- | --- |
| `renovate-validate` | Bash, Renovate CLI and validator, jq, mktemp, tee, rm | Repository checkout; `GITHUB_COM_TOKEN` for presets | Exit status and optional `reason` output |
| `renovate-lookup` | Bash, Renovate CLI, jq, OpenSSL, mktemp, cp, tail, rm | Repository checkout; `GITHUB_COM_TOKEN` for lookups | Exit status, optional `reason`, and summary |
| `renovate-monitor` | Bash, gh, jq, grep, AWK, mktemp, rm | `GH_REPO`, `GH_TOKEN`, GitHub repository/run context | Exit status, summary, and health issue operations |

GitHub supplies `GITHUB_OUTPUT` and `GITHUB_STEP_SUMMARY`. Run each action from the repository root.
The configuration path is `renovate.json`. The action script is resolved through `github.action_path`.
Keep tools in the caller's job image; local tests and actions then use the same Renovate installation.
The image remains a dependency that Renovate can update. Different consumers may use different image versions.

Validation and lookup jobs require `contents: read`. The monitor job also requires `issues: write`.
Provide credentials through environment variables, not script text. Do not use `pull_request_target` to run
untrusted repository code with write credentials.

## Inputs and outputs

Validate and lookup have no policy inputs. Their `reason` output is empty on success and contains a diagnostic
when the script identifies a failure. Unexpected failures may have no reason; consumers must check the job result.

Monitor requires `validation-result` and `lookup-result`, taken from `needs.<job>.result`.
Optional `validation-reason` and `lookup-reason` default to empty strings. Monitor has no additional outputs.
A failed local test after a successful action still fails the job; monitor reports the job status when no reason exists.

## Health behavior

Validation uses `--strict --no-global` and resolves shared presets. Lookup retries soft lookup failures once,
using a fresh cache. Rate limits and errors remain failures.

Monitor retains the canonical exceptions for the two timestamp-optional notices and the known package lookup warning.
Recognized warnings remain visible in the summary, including when another problem fails the run.
A successful local lookup does not prove that hosted Renovate has recovered.

The first health incident creates an issue. Repeated failures add comments to the existing issue.
A successful health run comments and closes it; the issue is not deleted.
A successful PR validation alone does not close the issue: monitor runs only on schedule or manual dispatch.
With Issues disabled, monitor skips Dashboard inspection and issue operations but still checks both job results.
The summary explicitly records this partial inspection.

Set the repository variable `RENOVATE_HEALTH_CHECK` to `false` to disable lookup and monitor.
Validation remains active. Close an existing incident manually after opting out.
Cancellation does not count as recovery.

## Caller example

The pilot uses the following workflow. Preserve each consumer's cron, branch filters, image, and local policy tests.
The test-suite step belongs to this pilot and is not a requirement for other consumers.
When these actions are published, replace local references with approved, versioned Workflow Hub references.

```yaml
name: Validate Renovate Config

on:
  push:
    paths:
      - renovate.json
      - .github/workflows/renovate-config-lint.yaml
      - .github/actions/renovate-validate/**
      - .github/actions/renovate-lookup/**
      - .github/actions/renovate-monitor/**
      - .github/tests/renovate-actions/**
  pull_request:
    paths:
      - renovate.json
      - .github/workflows/renovate-config-lint.yaml
      - .github/actions/renovate-validate/**
      - .github/actions/renovate-lookup/**
      - .github/actions/renovate-monitor/**
      - .github/tests/renovate-actions/**
  schedule:
    # Choose one stable Monday slot in 06:00-10:59 UTC for this repository.
    # Avoid reusing this example unchanged across repositories.
    - cron: "17 8 * * 1"
  workflow_dispatch: {}

permissions: {}

jobs:
  validate-renovate-config:
    name: Validate renovate.json
    runs-on: ubuntu-latest
    outputs:
      reason: ${{ steps.validate.outputs.reason }}
    container:
      image: renovate/renovate:43.285.4@sha256:bd7d8f646bf9d22aea995eaad06ec26c3f4fd4efbc36826024f5653006c9e7b1
      options: --user 0
    permissions:
      contents: read
    steps:
      - name: Checkout sources
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Validate configuration and resolve shared presets
        id: validate
        uses: ./.github/actions/renovate-validate
        env:
          GITHUB_COM_TOKEN: ${{ github.token }}

      - name: Test Renovate actions
        shell: bash
        run: python3 -m unittest discover -s .github/tests/renovate-actions -v

  lookup-renovate-dependencies:
    # Set the Actions variable RENOVATE_HEALTH_CHECK to false when this
    # repository intentionally does not run Renovate. Validation remains active
    # so local and inherited configuration errors are still reported.
    name: Look up Renovate dependencies
    if: >-
      (github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')
      && vars.RENOVATE_HEALTH_CHECK != 'false'
    runs-on: ubuntu-latest
    outputs:
      reason: ${{ steps.lookup.outputs.reason }}
    container:
      image: renovate/renovate:43.285.4@sha256:bd7d8f646bf9d22aea995eaad06ec26c3f4fd4efbc36826024f5653006c9e7b1
      options: --user 0
    permissions:
      contents: read
    steps:
      - name: Checkout sources
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Look up dependencies
        id: lookup
        uses: ./.github/actions/renovate-lookup
        env:
          GITHUB_COM_TOKEN: ${{ github.token }}

  monitor-renovate:
    name: Monitor Renovate health
    if: >-
      ${{ !cancelled()
      && (github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')
      && vars.RENOVATE_HEALTH_CHECK != 'false' }}
    needs:
      - validate-renovate-config
      - lookup-renovate-dependencies
    runs-on: ubuntu-latest
    concurrency:
      group: renovate-health-${{ github.repository }}
      cancel-in-progress: false
    permissions:
      contents: read
      issues: write
    env:
      GH_REPO: ${{ github.repository }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - name: Checkout sources
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Inspect Dependency Dashboard and report health
        uses: ./.github/actions/renovate-monitor
        with:
          validation-result: ${{ needs.validate-renovate-config.result }}
          lookup-result: ${{ needs.lookup-renovate-dependencies.result }}
          validation-reason: ${{ needs.validate-renovate-config.outputs.reason }}
          lookup-reason: ${{ needs.lookup-renovate-dependencies.outputs.reason }}
```

## Repository-specific tests

Keep policy tests in the caller after the validation action. For example, telemetry can retain these steps:

```yaml
- name: Test minimum Go version policy
  run: node .github/scripts/test-renovate-go-minimum.mjs
- name: Test automerge policy
  run: node .github/scripts/test-renovate-automerge.mjs
```

Do not add these steps to repositories that do not own the scripts.
Preserve their trigger paths. Monitoring operator's extraction test also retains its original environment and paths.
Do not set `continue-on-error` on required local tests.

## Local verification

The pilot suite requires Python 3, PyYAML, Bash, jq, and OpenSSL.
It runs the real shell scripts with local CLI substitutes, without inheriting authentication credentials.
The substitutes never fall back to the GitHub API.

```bash
python3 -m unittest discover -s .github/tests/renovate-actions -v
shellcheck .github/actions/renovate-{validate,lookup,monitor}/run.sh
actionlint .github/workflows/renovate-config-lint.yaml
```

These checks do not execute GitHub's composite-action engine.
Live verification must confirm outputs after failure, job results, permissions, event conditions, and issue lifecycle.
Review the complete changeset before authorizing any push or GitHub test.
