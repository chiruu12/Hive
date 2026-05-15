"""Agent profile - YAML-driven agent configuration."""

import importlib.resources
from pathlib import Path

import yaml
from pydantic import BaseModel


def default_profiles_dir() -> Path:
    """Find bundled profiles: check CWD first, then package data."""
    cwd_profiles = Path.cwd() / "profiles"
    if cwd_profiles.exists():
        return cwd_profiles
    try:
        ref = importlib.resources.files("hive") / "profiles"
        return Path(str(ref))
    except (TypeError, FileNotFoundError):
        return cwd_profiles


class Personality(BaseModel):
    """Agent personality configuration."""

    traits: list[str] = []
    style: str = ""


class AgentProfile(BaseModel):
    """Complete agent definition loaded from YAML."""

    name: str
    role: str
    model: str = ""
    personality: Personality = Personality()
    tools: list[str] = []
    workspace: str = "./workspaces/{name}"
    autonomy: str = "medium"  # low, medium, high
    max_steps: int = 20
    temperature: float = 0.0
    max_tokens: int = 4096
    max_cost_usd: float = 0.0
    system_prompt: str = ""
    skills: list[str] = []

    @classmethod
    def from_yaml(cls, path: Path) -> "AgentProfile":
        """Load agent profile from a YAML file."""
        from hive.config import get_config

        with open(path) as f:
            data = yaml.safe_load(f)
        profile = cls(**data)
        if not profile.model:
            profile.model = get_config().model.default_model
        return profile

    @classmethod
    def from_preset(cls, preset_name: str, profiles_dir: Path) -> "AgentProfile":
        """Load a preset agent profile by name."""
        path = profiles_dir / f"{preset_name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"No preset found: {preset_name}")
        return cls.from_yaml(path)

    def resolve_workspace(self) -> str:
        """Resolve workspace path, substituting {name} placeholder."""
        return self.workspace.replace("{name}", self.name)

    def build_system_prompt(self, economy_enabled: bool = True) -> str:
        """Build the full system prompt including personality and skills."""
        parts = [
            f"You are an autonomous agent named {self.name}.",
            f"Role: {self.role}.",
            "You live in a persistent simulated world.",
        ]
        if economy_enabled:
            parts.append(
                "You participate in an economy, pursue goals, earn money, and learn skills.",
            )
        else:
            parts.append("You make decisions and pursue goals autonomously.")
        parts.append("Always respond in the exact JSON format requested. Never break character.")

        if self.personality.traits:
            traits_str = ", ".join(self.personality.traits)
            parts.append(f"Personality: {traits_str}")

        if self.personality.style:
            parts.append(f"Communication style: {self.personality.style}")

        if self.system_prompt:
            parts.append(self.system_prompt.strip())

        if self.skills:
            from hive.agents.skills import load_skills

            skills_context = load_skills(self.skills)
            if skills_context:
                parts.append(f"--- Skills & Methodologies ---\n{skills_context}")

        return "\n\n".join(parts)
