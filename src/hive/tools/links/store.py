"""First-class named-link store: a stable ``name -> URL`` mapping.

Unlike the search-based link tools (which write to semantic memory), this is a
small, exact, enumerable store of named links -- the model a host app wants when
a user says "save my github as X" / "open my github". It is backed by a single
JSON file with atomic writes and corrupt-file recovery, and is usable both as a
plain library API and behind the ``@tool()`` methods on
:class:`~hive.tools.links.toolkit.LinkToolkit`, so a host and an agent operate on
one source of truth.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_SEP_RE = re.compile(r"[\s_]+")
_DASH_RE = re.compile(r"-+")


def normalize_name(name: str) -> str:
    """Normalize a display name to a stable lookup key.

    Lowercased, with runs of spaces/underscores/hyphens collapsed to a single
    ``-`` and stripped of leading/trailing dashes. ``"My GitHub"`` and
    ``"my_github"`` both normalize to ``"my-github"``.
    """
    key = _SEP_RE.sub("-", name.strip().lower())
    key = _DASH_RE.sub("-", key)
    return key.strip("-")


@dataclass(frozen=True)
class NamedLink:
    """A named link: its display ``name`` and ``url``."""

    name: str
    url: str


class NamedLinkStore:
    """A persistent ``name -> URL`` map backed by a JSON file.

    The store is keyed by the normalized name (see :func:`normalize_name`) while
    preserving the original display name. Writes are atomic (temp file + rename)
    and a corrupt file is backed up and reset rather than wedging the store.

    Args:
        path: JSON file location. A host can point this at its own path so the
            store is shared with the host's UI.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._links: dict[str, dict[str, str]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._links = {}
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                if isinstance(raw, dict):
                    for key, entry in raw.items():
                        if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                            self._links[key] = {
                                "name": str(entry.get("name", key)),
                                "url": entry["url"],
                            }
            except (json.JSONDecodeError, OSError, ValueError) as e:
                # A corrupt file shouldn't wedge the store: back it up and reset.
                logger.warning(
                    "named-link store at %s is unreadable (%s); backing up and resetting",
                    self._path,
                    e,
                )
                backup = self._path.with_suffix(self._path.suffix + ".corrupt")
                try:
                    self._path.replace(backup)
                except OSError:
                    pass
        self._loaded = True

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._links, indent=2, sort_keys=True))
        tmp.replace(self._path)

    def save(self, name: str, url: str) -> NamedLink:
        """Upsert a named link. Raises ``ValueError`` on an empty name or a
        non-http(s) URL."""
        key = normalize_name(name)
        if not key:
            raise ValueError("name must not be empty")
        url = url.strip()
        if not _SCHEME_RE.match(url):
            raise ValueError(f"url must start with http:// or https:// (got {url!r})")
        self._load()
        entry = {"name": name.strip(), "url": url}
        self._links[key] = entry
        self._save()
        return NamedLink(name=entry["name"], url=entry["url"])

    def get(self, name: str) -> str | None:
        """Return the URL for an exact (normalized) name, or ``None``."""
        self._load()
        entry = self._links.get(normalize_name(name))
        return entry["url"] if entry else None

    def list(self) -> list[dict[str, str]]:
        """Return all named links as ``[{"name", "url"}]`` in deterministic
        (normalized-key) order."""
        self._load()
        return [
            {"name": entry["name"], "url": entry["url"]} for _, entry in sorted(self._links.items())
        ]

    def remove(self, name: str) -> bool:
        """Remove a named link. Returns whether something was removed."""
        self._load()
        key = normalize_name(name)
        if key in self._links:
            del self._links[key]
            self._save()
            return True
        return False
