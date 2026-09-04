# Extract Renovate lint scripts into three composite actions

Local draft only. Do not publish before the pilot changeset review and authorized GitHub verification.

## Why

Copies of `renovate-config-lint.yaml` contain duplicated validation, lookup, and health scripts.
Consumers can update versioned action references with Renovate, but they cannot update arbitrary copied shell blocks
that way. Keep the workflow's three jobs and move their scripts into actions.

The pilot is in `Netcracker/qubership-observability-examples`, based on
`4578dd4ca7b4d23bc561dbb9a664d70d5e3d18a9` and the canonical template at
`Netcracker/.github@02eb2e234b8c777bf00885eb696ad0d5705b5847`.

## Proposed contract

| Local action | Inputs | Outputs and effects |
| --- | --- | --- |
| `renovate-validate` | Prepared checkout and Renovate environment | Exit status; optional `reason` |
| `renovate-lookup` | Prepared checkout and Renovate environment | Exit status; optional `reason`; summary |
| `renovate-monitor` | `validation-result`, `lookup-result`, optional `validation-reason`, `lookup-reason` | Exit status; summary; health issue creation, comments, and closure |

These are composite actions, not self-contained runtimes. They do not install tools or configure containers.
The caller supplies checkout, credentials, and the tools listed in `.github/actions/README.md`.
Renovate image versions remain dependencies of caller jobs; consumers need not share one fixed version.
Public paths and release refs must be agreed with Workflow Hub maintainers before publication.

## Required behavior

- Keep strict validation and shared preset resolution. Rate limits and unresolved configuration are failures.
- Keep one retry for soft dependency lookup failures, with a fresh cache for the second attempt.
- Consume the result of each entire job, including local tests after an action.
  A failure without `reason` must report the job status instead of reporting success.
- Preserve canonical Dashboard handling. Known lookup warnings do not independently fail health when local lookup passes.
  The two known timestamp-optional notices remain allowed. Recognized warnings stay visible in the summary.
- Unknown problems, errored updates, failed validation, and failed lookup still fail health.
- With Issues disabled, skip Dashboard/issue operations, report the limitation, and retain both job results.
- Create a health issue on the first failure, comment on repeated failures, and comment/close after recovery.
  Do not delete issues. A green PR validation alone does not close an incident.
- Keep opt-out and cancellation conditions in the caller. Opt-out does not disable validation.
- Keep cron, branch filters, permissions, and repository-specific policy tests in caller workflows.
  Use top-level `permissions: {}` and explicit job permissions.

No new policy switches, custom test hooks, global image version, or separate observability workflow hub are proposed.
Archived repositories are excluded from automatic migration.

## Verification completed locally

- 16 unittest methods, including table-driven cases, pass on macOS and in the pinned Renovate Linux image.
- Linux tests run without network access or credentials, using a read-only checkout mount.
- Sensitivity checks fail when validation reason output, lookup retry, or validation-result handling is removed.
- Shell syntax, ShellCheck, YAML parsing, and actionlint v1.7.12 pass.

These tests exercise shell scripts using local CLI substitutes. They do not prove GitHub's runtime output propagation.

## Required GitHub acceptance before publication

After the user reviews the complete changeset and authorizes live testing, verify:

- PR validation and manual health execution on the reviewed SHA.
- Outputs after action failure and the whole-job result after a failing local test.
- Actual permissions, opt-out, cancellation, and disabled-Issues behavior in an approved test context.
- Real health issue creation, repeated comment, and automatic closure without touching unrelated incidents.
- Schedule behavior, recorded separately from manual dispatch.

GitHub runs and live issue lifecycle have not been tested yet. No PR or release has been published.
The passing local suite is not full pilot acceptance.
