"""Health checks for hive doctor."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from hive.config import get_env


@dataclass
class CheckResult:
    name: str
    status: Literal["ok", "warn", "fail"]
    message: str
    fix: str = field(default="")


def check_python_version() -> CheckResult:
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 11):
        return CheckResult("Python version", "ok", version_str)
    return CheckResult(
        "Python version",
        "fail",
        f"{version_str} (need >=3.11)",
        fix="Install Python 3.11+ from python.org",
    )


def check_anthropic_key() -> CheckResult:
    key = get_env("ANTHROPIC_API_KEY")
    if key:
        masked = key[:8] + "..." + key[-4:]
        return CheckResult("Anthropic API key", "ok", f"Set ({masked})")
    return CheckResult(
        "Anthropic API key",
        "warn",
        "Not set",
        fix="Set ANTHROPIC_API_KEY in .env or environment",
    )


def check_openai_key() -> CheckResult:
    key = get_env("OPENAI_API_KEY")
    if key:
        masked = key[:8] + "..." + key[-4:]
        return CheckResult("OpenAI API key", "ok", f"Set ({masked})")
    return CheckResult(
        "OpenAI API key",
        "warn",
        "Not set (optional)",
        fix="Set OPENAI_API_KEY in .env if using OpenAI models",
    )


def check_groq_key() -> CheckResult:
    key = get_env("GROQ_API_KEY")
    if key:
        masked = key[:8] + "..." + key[-4:]
        return CheckResult("Groq API key", "ok", f"Set ({masked})")
    return CheckResult(
        "Groq API key",
        "warn",
        "Not set (optional)",
        fix="Set GROQ_API_KEY in .env if using Groq models",
    )


def check_local_model(name: str, url: str) -> CheckResult:
    try:
        import httpx

        resp = httpx.get(f"{url}/models", timeout=2.0)
        if resp.status_code == 200:
            return CheckResult(name, "ok", f"Reachable at {url}")
        return CheckResult(
            name,
            "warn",
            f"HTTP {resp.status_code}",
            fix=f"Check {name} is running",
        )
    except Exception:
        return CheckResult(
            name,
            "warn",
            "Not reachable (optional)",
            fix=f"Start {name} if you want local models",
        )


def check_hive_dir(hive_dir: Path) -> CheckResult:
    if not hive_dir.exists():
        return CheckResult(
            ".hive directory",
            "fail",
            "Not found",
            fix="Run `hive init` to create it",
        )
    required = ["hive.db", "config.yaml"]
    missing = [f for f in required if not (hive_dir / f).exists()]
    if missing:
        return CheckResult(
            ".hive directory",
            "warn",
            f"Missing: {', '.join(missing)}",
            fix="Run `hive init` to recreate",
        )
    return CheckResult(".hive directory", "ok", "Present and valid")


def check_sqlite_integrity(hive_dir: Path) -> CheckResult:
    db_path = hive_dir / "hive.db"
    if not db_path.exists():
        return CheckResult(
            "SQLite database",
            "warn",
            "No database yet",
        )
    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        if result and result[0] == "ok":
            return CheckResult(
                "SQLite database",
                "ok",
                "Integrity check passed",
            )
        return CheckResult(
            "SQLite database",
            "fail",
            f"Integrity: {result}",
        )
    except Exception as e:
        return CheckResult("SQLite database", "fail", str(e))


def check_dependencies() -> CheckResult:
    missing = []
    for pkg in [
        "typer",
        "rich",
        "aiosqlite",
        "pydantic",
        "anthropic",
        "openai",
        "yaml",
        "httpx",
    ]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return CheckResult(
            "Dependencies",
            "fail",
            f"Missing: {', '.join(missing)}",
            fix="Run `uv sync` or `pip install hive-agent`",
        )
    return CheckResult("Dependencies", "ok", "All installed")


def check_config_valid() -> CheckResult:
    """Validate config values against field validators."""
    try:
        from hive.config import HiveConfig

        cfg = HiveConfig()
        env_warnings = cfg.validate_environment()
        if env_warnings:
            return CheckResult(
                "Config validation",
                "warn",
                "; ".join(env_warnings),
                fix="Set the required API key in .env or environment",
            )
        return CheckResult("Config validation", "ok", "All values valid")
    except Exception as e:
        return CheckResult(
            "Config validation",
            "fail",
            str(e),
            fix="Check .hive/config.yaml for invalid values",
        )


def run_all_checks(hive_dir: Path | None = None) -> list[CheckResult]:
    hive = hive_dir or (Path.cwd() / ".hive")
    return [
        check_python_version(),
        check_dependencies(),
        check_config_valid(),
        check_anthropic_key(),
        check_openai_key(),
        check_groq_key(),
        check_local_model("Ollama", "http://localhost:11434/v1"),
        check_local_model("LM Studio", "http://localhost:1234/v1"),
        check_hive_dir(hive),
        check_sqlite_integrity(hive),
    ]
