"""The scheduled-workflow dispatcher (infra/aws/dispatcher/handler.py), without network."""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "dispatcher", Path(__file__).resolve().parents[1] / "infra/aws/dispatcher/handler.py"
)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def test_request_targets_workflow_dispatch_on_main():
    req = d.build_request("owner/repo", "ingest.yml", "t0k3n", {"x": "1"})
    assert (
        req.full_url
        == "https://api.github.com/repos/owner/repo/actions/workflows/ingest.yml/dispatches"
    )
    assert req.get_method() == "POST"
    assert json.loads(req.data) == {"ref": "main", "inputs": {"x": "1"}}
    assert req.headers["Authorization"] == "Bearer t0k3n"


def test_only_allow_listed_workflows_can_be_dispatched():
    with pytest.raises(ValueError, match="not allowed"):
        d.build_request("owner/repo", "rollback.yml", "t")


def test_success_returns_status(monkeypatch):
    class Resp(io.BytesIO):
        status = 204

    monkeypatch.setattr(d.urllib.request, "urlopen", lambda req, timeout: Resp(b""))
    assert d.dispatch("owner/repo", "monitor.yml", "t") == 204


def test_github_error_raises_without_leaking_the_token(monkeypatch):
    def fail(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"Bad credentials"}')
        )

    monkeypatch.setattr(d.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="401") as exc:
        d.dispatch("owner/repo", "forecast.yml", "secret-token")
    assert "secret-token" not in str(exc.value)
