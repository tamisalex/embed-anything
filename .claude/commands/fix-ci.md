---
name: fix-ci
description: Lists all open PRs, picks the highest-priority failing one, analyzes GitHub Actions logs, fixes the code, and pushes until CI passes.
disable-model-invocation: true
---

You are a CI fix agent for the embed-anything repo. Your job is to triage all open PRs, pick the highest-priority one with a failing build, then iterate fixes until CI passes.

## Step 1 — Triage open PRs

Run:
```
gh pr list --state open --json number,title,headRefName,statusCheckRollup,updatedAt,author
```

For each PR, determine its CI state:
- `SUCCESS` — all checks green, skip
- `PENDING` / `IN_PROGRESS` — build running, note but deprioritize
- `FAILURE` / `ERROR` — needs fixing, add to the fix queue

If there are no failing PRs, report all PRs are green and stop.

## Step 2 — Pick the highest-priority PR

Rank failing PRs by these criteria (highest first):

1. **Mergeable + authored by a human** (not a bot) — most urgent
2. **Most recently updated** — signals active work
3. **Fewest commits ahead of main** — simpler to fix

State your reasoning clearly: "Picking PR #N (<title>) because …"

Check out the PR branch:
```
gh pr checkout <number>
```

## Step 3 — Fetch failure logs

```
gh run list --branch <head-branch> --limit 3 --json databaseId,status,conclusion,name
```

Take the most recent failed run ID, then:
```
gh run view <run-id> --log-failed
```

Also run `gh run view <run-id>` to see which job/step failed.

Focus on the first error. If the log is very long, look for lines matching `Error`, `error`, `FAILED`, `Traceback`, `exit code`.

## Step 4 — Analyze the failure

Read the relevant source files. Common failure patterns in this repo:

- **Docker build / pip install**: Check the Dockerfile and pyproject.toml for the affected package — bad dep versions, missing extras, or wrong install path.
- **Python import error**: Verify the import path exists in the package source.
- **Prefect deploy**: Check `packages/embed-pipeline/prefect.yaml` and the flow entrypoint (`src/embed_pipeline/flow.py`).
- **ECS / AWS deploy**: Usually infra/IAM — do NOT attempt to fix, escalate to user.
- **Ruff lint**: Read the error lines and fix flagged code.
- **Test failures**: Read the assertion error and fix the code or test.

State the root cause before touching anything.

## Step 5 — Fix, commit, and push

Make the minimal change. Then:
```
git add <specific changed files>
git commit -m "<short fix description>"
git push
```

Rules:
- Stage only files you changed — never `git add .`
- No `--no-verify`
- No force push
- One logical fix per commit

## Step 6 — Wait and re-check

Wait ~60 seconds, then repeat from **Step 3** for the same PR.

Go back to **Step 2** (re-triage) only after the current PR either passes or is declared unfixable.

## Stopping conditions

- **Success**: all checks on the target PR are green → report done, optionally move to the next failing PR.
- **Unfixable**: failure is in AWS/ECS infra, or you've pushed the same type of fix twice without progress → stop, explain the failure and why it can't be auto-fixed.
- **Max iterations**: 5 push-and-wait cycles on a single PR without success → summarize attempts and stop.

## Key files

| Purpose | Path |
|---|---|
| CI workflow | `.github/workflows/docker_build_action.yaml` |
| API Dockerfile | `packages/embed-api/Dockerfile` |
| Pipeline Dockerfile | `packages/embed-pipeline/Dockerfile` |
| Pipeline deps | `packages/embed-pipeline/pyproject.toml` |
| API deps | `packages/embed-api/pyproject.toml` |
| Shared core deps | `packages/embed-core/pyproject.toml` |
| Prefect config | `packages/embed-pipeline/prefect.yaml` |

Never modify Terraform or AWS IAM resources.
