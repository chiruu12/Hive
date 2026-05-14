"""Skills loader — load markdown skill files and inject into agent context."""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def default_skills_dir() -> Path:
    """Find bundled skills: check CWD first, then package data."""
    cwd_skills = Path.cwd() / "skills"
    if cwd_skills.exists():
        return cwd_skills
    try:
        ref = importlib.resources.files("hive") / "skills"
        return Path(str(ref))
    except (TypeError, FileNotFoundError):
        return cwd_skills


def load_skill(name: str, skills_dir: Path | None = None) -> str | None:
    """Load a skill's markdown content by name."""
    search_dir = skills_dir or default_skills_dir()
    path = search_dir / f"{name}.md"
    if path.exists():
        return path.read_text().strip()
    dashed = search_dir / f"{name.replace('_', '-')}.md"
    if dashed.exists():
        return dashed.read_text().strip()
    return None


def load_skills(names: list[str], skills_dir: Path | None = None) -> str:
    """Load multiple skills and combine into a context string."""
    if not names:
        return ""
    sections: list[str] = []
    for name in names:
        content = load_skill(name, skills_dir)
        if content:
            sections.append(f"## Skill: {name}\n{content}")
        else:
            logger.debug("Skill not found: %s", name)
    return "\n\n".join(sections)
