"""Start a GitHub Actions workflow on schedule (EventBridge Scheduler -> this -> GitHub).

GitHub's own cron skipped most runs on some days (docs/incidents.md). Scheduler fires
on time, but cannot call GitHub's API itself, so each schedule invokes this function
with {"workflow": "<file>.yml", "inputs": {...}} and it calls workflow_dispatch.
Dispatched runs start immediately; they are not subject to cron's dropped runs.

The GitHub token (fine-grained, Actions read/write on this one repository) is read
from an SSM SecureString at runtime and never stored in code or Terraform state.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API = "https://api.github.com"
ALLOWED_WORKFLOWS = {"ingest.yml", "forecast.yml", "monitor.yml", "deploy.yml"}


def build_request(
    repo: str, workflow: str, token: str, inputs: dict | None = None, ref: str = "main"
) -> urllib.request.Request:
    if workflow not in ALLOWED_WORKFLOWS:
        raise ValueError(f"workflow {workflow!r} is not allowed")
    body = json.dumps({"ref": ref, "inputs": inputs or {}}).encode()
    return urllib.request.Request(
        f"{API}/repos/{repo}/actions/workflows/{workflow}/dispatches",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ne-demand-dispatcher",
        },
    )


def dispatch(repo: str, workflow: str, token: str, inputs: dict | None = None) -> int:
    req = build_request(repo, workflow, token, inputs)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        # Raise so the schedule's retry policy applies and the failure shows in metrics.
        detail = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"GitHub returned {e.code} dispatching {workflow}: {detail}") from None


def _get_token() -> str:  # pragma: no cover - AWS wiring
    # Read on every run (a few calls an hour), so a rotated token takes effect at once
    # instead of a warm instance holding the old one.
    import boto3

    return boto3.client("ssm").get_parameter(Name=os.environ["TOKEN_PARAM"], WithDecryption=True)[
        "Parameter"
    ]["Value"]


def handler(event, context):  # pragma: no cover - thin AWS wiring around dispatch()
    workflow = event["workflow"]
    status = dispatch(os.environ["REPO"], workflow, _get_token(), event.get("inputs"))
    print(json.dumps({"workflow": workflow, "status": status}))
    return {"workflow": workflow, "status": status}
