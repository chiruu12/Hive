"""Tests for per-agent provider/profile caching across cycles (Phase 2 B3)."""

from __future__ import annotations

import os
from pathlib import Path

from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon


def _agent(model: str = "mock-model", agent_id: str = "a1") -> AgentState:
    return AgentState(
        agent_id=agent_id, name="coder", role="t", model=model, status=AgentStatus.IDLE
    )


def _daemon(tmp_path: Path) -> HiveDaemon:
    return HiveDaemon(tmp_path / ".hive", heartbeat=0, logs_dir=tmp_path / "logs")


class TestProviderCache:
    def test_provider_reused_then_rebuilt_on_model_change(self, tmp_path, monkeypatch) -> None:
        calls: list[str] = []

        def fake_create(model: str) -> object:
            calls.append(model)
            return object()

        monkeypatch.setattr("hive.daemon.loop.create_runtime_provider", fake_create)
        daemon = _daemon(tmp_path)

        p1 = daemon._get_provider(_agent(model="m1"))
        p2 = daemon._get_provider(_agent(model="m1"))
        assert p1 is p2  # reused across cycles
        assert calls == ["m1"]  # built only once

        p3 = daemon._get_provider(_agent(model="m2"))  # model changed -> rebuild
        assert p3 is not p1
        assert calls == ["m1", "m2"]


class TestProfileCache:
    def test_profile_cached_and_invalidated_on_mtime(self, tmp_path) -> None:
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        pfile = profiles_dir / "coder.yaml"
        pfile.write_text("name: coder\nrole: engineer\n")

        daemon = _daemon(tmp_path)
        cfg = HiveConfig()
        cfg.profiles_dir = str(profiles_dir)
        set_config(cfg)

        pr1 = daemon._load_profile("coder")
        pr2 = daemon._load_profile("coder")
        assert pr1 is pr2  # cached, no re-read
        assert pr1.role == "engineer"

        # Edit the file and bump its mtime -> cache invalidates, profile reloads.
        pfile.write_text("name: coder\nrole: senior engineer\n")
        st = pfile.stat()
        os.utime(pfile, (st.st_atime + 100, st.st_mtime + 100))

        pr3 = daemon._load_profile("coder")
        assert pr3 is not pr1
        assert pr3.role == "senior engineer"

    def test_missing_profile_falls_back_and_caches(self, tmp_path) -> None:
        daemon = _daemon(tmp_path)
        cfg = HiveConfig()
        cfg.profiles_dir = str(tmp_path / "empty")
        (tmp_path / "empty").mkdir()
        set_config(cfg)

        pr1 = daemon._load_profile("ghost")
        pr2 = daemon._load_profile("ghost")
        assert pr1 is pr2
        assert pr1.role == "general agent"
