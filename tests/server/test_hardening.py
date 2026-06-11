"""Tests for server hardening: API-key auth, CORS, pagination, session TTL."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from hive.errors import AgentNotFoundError  # noqa: E402
from hive.memory.store import HiveStore  # noqa: E402
from hive.server.app import create_app  # noqa: E402
from hive.server.deps import SessionService  # noqa: E402

_REPO_PROFILES = Path(__file__).resolve().parents[2] / "profiles"


def _make_client(tmp_path: Path, config_yaml: str = "") -> TestClient:
    shutil.copytree(_REPO_PROFILES, tmp_path / "profiles", dirs_exist_ok=True)
    if config_yaml:
        (tmp_path / ".hive").mkdir(exist_ok=True)
        (tmp_path / ".hive" / "config.yaml").write_text(config_yaml)
    return TestClient(create_app(root=tmp_path))


@pytest.fixture
def secured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.chdir(tmp_path)
    with _make_client(tmp_path, "server:\n  api_key: testkey123\n") as c:
        yield c


@pytest.fixture
def open_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.chdir(tmp_path)
    with _make_client(tmp_path) as c:
        yield c


class TestApiKeyAuth:
    def test_data_routes_require_key(self, secured: TestClient) -> None:
        assert secured.get("/agents").status_code == 401
        assert secured.get("/agents", headers={"X-Hive-Key": "wrong"}).status_code == 401
        assert secured.get("/agents", headers={"X-Hive-Key": "testkey123"}).status_code == 200

    def test_probe_and_static_shells_exempt(self, secured: TestClient) -> None:
        # Orchestrator probes and the static UI/docs shells carry no data.
        assert secured.get("/healthz").status_code == 200
        assert secured.get("/").status_code == 200
        assert secured.get("/openapi.json").status_code == 200

    def test_mutations_require_key(self, secured: TestClient) -> None:
        assert secured.post("/agents", json={"preset": "coder"}).status_code == 401
        ok = secured.post("/agents", json={"preset": "coder"}, headers={"X-Hive-Key": "testkey123"})
        assert ok.status_code == 201

    def test_open_by_default(self, open_client: TestClient) -> None:
        assert open_client.get("/agents").status_code == 200


class TestCors:
    def test_cors_headers_when_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        cfg = 'server:\n  cors_origins: ["http://example.com"]\n'
        with _make_client(tmp_path, cfg) as c:
            resp = c.get("/agents", headers={"Origin": "http://example.com"})
            assert resp.headers.get("access-control-allow-origin") == "http://example.com"

    def test_no_cors_by_default(self, open_client: TestClient) -> None:
        resp = open_client.get("/agents", headers={"Origin": "http://example.com"})
        assert "access-control-allow-origin" not in resp.headers


class TestPagination:
    def test_agents_limit_and_offset(self, open_client: TestClient) -> None:
        for _ in range(3):
            assert open_client.post("/agents", json={"preset": "coder"}).status_code == 201
        assert len(open_client.get("/agents").json()) == 3
        assert len(open_client.get("/agents", params={"limit": 2}).json()) == 2
        assert len(open_client.get("/agents", params={"limit": 2, "offset": 2}).json()) == 1

    def test_limit_bounds_validated(self, open_client: TestClient) -> None:
        assert open_client.get("/agents", params={"limit": 0}).status_code == 422
        assert open_client.get("/agents", params={"limit": 1001}).status_code == 422


class TestSessionTtl:
    @pytest.mark.asyncio
    async def test_idle_sessions_expire_and_stop_resolving(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "hive.db")
        await store.initialize()
        await store.create_session("sess-idle", "a1", "t", user_id="alice", session_key="k1")

        # Simulate long idleness, then run the janitor with a 1-hour TTL.
        import aiosqlite

        stale = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        async with aiosqlite.connect(tmp_path / "hive.db") as db:
            await db.execute(
                "UPDATE sessions SET last_active = ? WHERE session_id = 'sess-idle'", (stale,)
            )
            await db.commit()

        counts = await store.cleanup(days=30, session_ttl_hours=1)
        assert counts["expired_sessions"] == 1

        svc = SessionService(store)
        with pytest.raises(AgentNotFoundError):
            await svc.resolve("alice", "a1", "t", session_id="sess-idle")
        # A session_key lookup falls through to a fresh session instead.
        new_id = await svc.resolve("alice", "a1", "t", session_key="k1")
        assert new_id != "sess-idle"

    @pytest.mark.asyncio
    async def test_ttl_zero_never_expires(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "hive.db")
        await store.initialize()
        await store.create_session("sess-keep", "a1", "t", user_id="alice")
        counts = await store.cleanup(days=30, session_ttl_hours=0)
        assert "expired_sessions" not in counts
        row = await store.get_session("sess-keep")
        assert row is not None and row["status"] == "running"
