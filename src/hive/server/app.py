"""FastAPI application factory for the Hive REST API (AgentOS surface)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI

from hive.config import HiveConfig, load_config
from hive.daemon.setup import ensure_hive_dirs
from hive.memory.store import HiveStore
from hive.server import ui
from hive.server.deps import ServerContext, SessionService, require_api_key
from hive.server.errors import register_error_handlers
from hive.server.routes import agents, approvals, sessions, system, tasks

logger = logging.getLogger(__name__)


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("hive-agent")
    except Exception:
        return "0.0.0"


def create_app(root: Path | None = None, with_daemon: bool = False) -> FastAPI:
    """Build the FastAPI app.

    Args:
        root: Project root containing ``.hive/``. Defaults to the CWD.
        with_daemon: Run the heartbeat loop in-process as a background task. When
            False (default), the server is a stateless control plane over the same
            ``hive.db`` an external ``hive start`` daemon drives.
    """
    project_root = root or Path.cwd()
    hive_dir = project_root / ".hive"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_hive_dirs(project_root)
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        config = load_config(hive_dir)
        ctx = ServerContext(
            root=project_root,
            hive_dir=hive_dir,
            store=store,
            config=config,
            sessions=SessionService(store),
        )

        daemon_task = None
        if with_daemon:
            from hive.daemon.loop import HiveDaemon

            ctx.daemon = HiveDaemon(hive_dir, logs_dir=project_root / "logs")
            daemon_task = asyncio.create_task(ctx.daemon.start())
            logger.info("Started in-process daemon")

        app.state.ctx = ctx
        try:
            yield
        finally:
            if ctx.daemon is not None:
                ctx.daemon.stop()
            if daemon_task is not None:
                # Await the cancelled task so the daemon's shutdown path (alarm
                # task teardown, shutdown checkpoints) completes before exit.
                daemon_task.cancel()
                with suppress(asyncio.CancelledError):
                    await daemon_task

    app = FastAPI(
        title="Hive AgentOS API",
        version=_version(),
        summary="REST control plane for Hive agents: spawn, run, stream, approve.",
        lifespan=lifespan,
        # Auth gate on every route (no-op until server.api_key is configured;
        # /healthz and the static UI/docs shells are exempt).
        dependencies=[Depends(require_api_key)],
    )
    register_error_handlers(app)
    # Middleware must be mounted at build time, before the lifespan runs, so
    # read the config eagerly here (the lifespan loads it again into the
    # process-global config).
    boot_config = HiveConfig.load(hive_dir if hive_dir.is_dir() else None)
    if boot_config.server.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=boot_config.server.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    for module in (agents, tasks, approvals, sessions, system, ui):
        app.include_router(module.router)
    return app
