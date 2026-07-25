"""Project scaffolding templates for ``hive new``."""

from __future__ import annotations

import re
from pathlib import Path

# ── Template definitions ──────────────────────────────────────────────────────

MINIMAL_CONFIG = """\
# Hive configuration — minimal single-agent setup
daemon:
  heartbeat: 30
economy:
  enabled: false
model:
  default_model: claude-sonnet-4-6
  temperature: 0.7
"""

MINIMAL_PROFILE = """\
name: assistant
role: General-purpose assistant
backstory: A helpful AI assistant that completes tasks efficiently.
"""

TEAM_CONFIG = """\
# Hive configuration — 3-agent team
daemon:
  heartbeat: 30
economy:
  enabled: false
model:
  default_model: claude-sonnet-4-6
  temperature: 0.7
"""

TEAM_PROFILES = {
    "architect": """\
name: architect
role: System architect
backstory: An experienced architect who designs clean, scalable systems.
""",
    "developer": """\
name: developer
role: Developer
backstory: A skilled developer who writes clean, tested code.
""",
    "reviewer": """\
name: reviewer
role: Code reviewer
backstory: A meticulous reviewer who catches bugs and enforces standards.
""",
}

RESEARCH_CONFIG = """\
# Hive configuration — research setup
daemon:
  heartbeat: 60
economy:
  enabled: false
model:
  default_model: claude-sonnet-4-6
  planning_model: claude-sonnet-4-6
  temperature: 0.9
"""

RESEARCH_PROFILES = {
    "researcher": """\
name: researcher
role: Research lead
backstory: An analytical researcher who explores topics deeply and synthesizes findings.
""",
    "analyst": """\
name: analyst
role: Data analyst
backstory: A detail-oriented analyst who validates findings with data.
""",
}

README_TEMPLATE = """\
# {name}

A Hive project created with `hive new --template {template}`.

## Quick Start

```bash
hive status        # Check agent status
hive start         # Start the daemon
hive watch         # Live TUI dashboard
```

## Configuration

Edit `.hive/config.yaml` to adjust settings.
Agent profiles are in `./profiles/` (where `hive start` and `hive spawn` look).
"""

# ── Validation ────────────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_project_name(name: str) -> str | None:
    """Return an error message if the name is invalid, else ``None``."""
    if not name:
        return "Project name cannot be empty."
    if not _NAME_RE.match(name):
        return f"Project name must be alphanumeric (with - or _): {name!r}"
    if len(name) > 64:
        return "Project name must be 64 characters or fewer."
    return None


# ── Scaffold logic ────────────────────────────────────────────────────────────

TEMPLATES = {"minimal", "team", "research"}


def scaffold_project(
    name: str,
    template: str,
    target: Path,
    force: bool = False,
) -> Path:
    """Create a ``.hive`` project directory.

    Returns the path to the created ``.hive`` directory.
    Raises ``FileExistsError`` if the directory exists and ``force`` is ``False``.
    Raises ``ValueError`` for invalid name or template.
    """
    err = validate_project_name(name)
    if err:
        raise ValueError(err)
    if template not in TEMPLATES:
        choices = ", ".join(sorted(TEMPLATES))
        raise ValueError(f"Unknown template {template!r}. Choose from: {choices}")

    hive_dir = target / ".hive"
    if hive_dir.exists() and not force:
        raise FileExistsError(f"Directory already exists: {hive_dir}")

    hive_dir.mkdir(parents=True, exist_ok=True)
    # Profiles live at the project root -- this is where `hive start`, `hive
    # spawn`, and default_profiles_dir() look. Writing template files here
    # overwrites same-named profiles but never deletes unrelated ones.
    profiles_dir = target / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    # Write config
    config_text = {
        "minimal": MINIMAL_CONFIG,
        "team": TEAM_CONFIG,
        "research": RESEARCH_CONFIG,
    }[template]
    (hive_dir / "config.yaml").write_text(config_text)

    # Write profiles
    if template == "minimal":
        (profiles_dir / "assistant.yaml").write_text(MINIMAL_PROFILE)
    elif template == "team":
        for pname, content in TEAM_PROFILES.items():
            (profiles_dir / f"{pname}.yaml").write_text(content)
    elif template == "research":
        for pname, content in RESEARCH_PROFILES.items():
            (profiles_dir / f"{pname}.yaml").write_text(content)

    # Write README
    (hive_dir / "README.md").write_text(README_TEMPLATE.format(name=name, template=template))

    return hive_dir
