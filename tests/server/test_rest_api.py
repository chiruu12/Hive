"""Integration tests for the Hive REST API (skipped without the [api] extra)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from hive.server.app import create_app  # noqa: E402

_REPO_PROFILES = Path(__file__).resolve().parents[2] / "profiles"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import shutil

    # default_profiles_dir() looks in CWD/profiles first; provide them there so
    # spawn works in the isolated tmp project (dev installs don't package them).
    shutil.copytree(_REPO_PROFILES, tmp_path / "profiles")
    monkeypatch.chdir(tmp_path)
    app = create_app(root=tmp_path)
    with TestClient(app) as c:
        yield c


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["database"] is True


def test_spawn_list_get_kill(client: TestClient) -> None:
    resp = client.post("/agents", json={"preset": "coder"})
    assert resp.status_code == 201
    agent_id = resp.json()["agent_id"]

    listing = client.get("/agents").json()
    assert any(a["agent_id"] == agent_id for a in listing)

    detail = client.get(f"/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "idle"

    assert client.delete(f"/agents/{agent_id}").status_code == 204
    assert client.get(f"/agents/{agent_id}").json()["status"] == "dead"


def test_get_unknown_agent_404(client: TestClient) -> None:
    assert client.get("/agents/nope").status_code == 404


def test_nudge(client: TestClient) -> None:
    agent_id = client.post("/agents", json={"preset": "coder"}).json()["agent_id"]
    resp = client.post(f"/agents/{agent_id}/nudge", json={"message": "hi"})
    assert resp.status_code == 202
    assert "nudge_id" in resp.json()


def test_session_isolation(client: TestClient) -> None:
    agent_id = client.post("/agents", json={"preset": "coder"}).json()["agent_id"]
    # Create a session as alice.
    resp = client.post(
        "/sessions",
        json={"agent_id": agent_id, "session_key": "chat-1"},
        headers={"X-Hive-User": "alice"},
    )
    assert resp.status_code == 201
    session_id = resp.json()["session_id"]

    # alice sees it; bob does not (404 cross-tenant).
    alice = {"X-Hive-User": "alice"}
    bob = {"X-Hive-User": "bob"}
    assert client.get(f"/sessions/{session_id}", headers=alice).status_code == 200
    assert client.get(f"/sessions/{session_id}", headers=bob).status_code == 404

    alice_sessions = client.get("/sessions", headers={"X-Hive-User": "alice"}).json()
    assert [s["session_id"] for s in alice_sessions] == [session_id]
    assert client.get("/sessions", headers={"X-Hive-User": "bob"}).json() == []


def test_approval_queue_and_resolution(client: TestClient, tmp_path: Path) -> None:
    import asyncio

    from hive.memory.store import HiveStore

    agent_id = client.post("/agents", json={"preset": "coder"}).json()["agent_id"]
    # Seed a pending approval via a fresh store on the same DB (its own connection),
    # so we don't reach into the app's running event loop from the test thread.
    store = HiveStore(tmp_path / ".hive" / "hive.db")
    asyncio.run(store.create_approval("ap-1", agent_id, "shell_exec", '{"cmd":"ls"}', "h1"))

    queue = client.get("/approvals").json()
    assert any(a["approval_id"] == "ap-1" for a in queue)

    resp = client.post(
        f"/agents/{agent_id}/approvals/ap-1", json={"decision": "approve"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    # Second resolution is a conflict.
    assert (
        client.post(f"/agents/{agent_id}/approvals/ap-1", json={"decision": "deny"}).status_code
        == 409
    )
