"""Generate standalone HTML run reports."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from hive.logging.reader import LogReader
from hive.tools.notepad import NotepadManager

CSS = """
:root { --bg: #1a1b26; --fg: #c0caf5; --dim: #565f89; --accent: #7aa2f7;
  --green: #9ece6a; --red: #f7768e; --yellow: #e0af68; --card: #24283b; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'SF Mono', 'Cascadia Code', monospace; background: var(--bg);
  color: var(--fg); padding: 2rem; max-width: 900px; margin: 0 auto; }
h1 { color: var(--accent); margin-bottom: 0.5rem; }
h2 { color: var(--accent); margin: 1.5rem 0 0.5rem; font-size: 1.1rem; }
h3 { color: var(--dim); margin: 1rem 0 0.3rem; font-size: 0.95rem; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.8rem; margin: 1rem 0; }
.stat { background: var(--card); padding: 0.8rem; border-radius: 6px; }
.stat .label { color: var(--dim); font-size: 0.75rem; text-transform: uppercase; }
.stat .value { font-size: 1.4rem; font-weight: bold; margin-top: 0.2rem; }
.card { background: var(--card); border-radius: 8px; padding: 1rem;
  margin: 0.8rem 0; }
.goal { padding: 0.4rem 0; border-bottom: 1px solid #2a2e42; }
.goal:last-child { border: none; }
.completed { color: var(--green); }
.abandoned { color: var(--red); }
.generated { color: var(--yellow); }
.tool { color: var(--dim); font-size: 0.85rem; padding: 0.2rem 0; }
.notepad { white-space: pre-wrap; font-size: 0.85rem; color: var(--dim);
  max-height: 300px; overflow-y: auto; }
.thread { margin: 0.5rem 0; padding: 0.5rem; background: #1e2030;
  border-radius: 4px; }
.msg { padding: 0.3rem 0; }
.msg .from { color: var(--accent); font-weight: bold; }
.msg .type { color: var(--dim); font-size: 0.8rem; }
.footer { margin-top: 2rem; color: var(--dim); font-size: 0.8rem;
  text-align: center; }
"""


def _esc(text: str) -> str:
    return html.escape(str(text))


def _build_agent_card(
    reader: LogReader,
    run_id: str,
    agent_id: str,
    notepad_mgr: NotepadManager | None,
    a2a_data: dict[str, list[dict[str, Any]]],
) -> str:
    goals = reader.get_agent_goals(run_id, agent_id)
    decisions = reader.get_agent_decisions(run_id, agent_id)
    tools = reader.get_agent_tools(run_id, agent_id)

    total_tokens = sum(d.input_tokens + d.output_tokens for d in decisions)
    total_cost = sum(d.cost_usd or 0 for d in decisions)
    name = agent_id.split("-")[0]

    parts = [f'<div class="card"><h2>{_esc(name)} ({_esc(agent_id[:20])})</h2>']
    parts.append('<div class="stats">')
    parts.append(
        f'<div class="stat"><div class="label">Goals</div>'
        f'<div class="value">{len(goals)}</div></div>'
    )
    parts.append(
        f'<div class="stat"><div class="label">Tools</div>'
        f'<div class="value">{len(tools)}</div></div>'
    )
    parts.append(
        f'<div class="stat"><div class="label">Tokens</div>'
        f'<div class="value">{total_tokens:,}</div></div>'
    )
    parts.append(
        f'<div class="stat"><div class="label">Cost</div>'
        f'<div class="value">${total_cost:.4f}</div></div>'
    )
    parts.append("</div>")

    if goals:
        parts.append("<h3>Goals</h3>")
        for g in goals[:10]:
            cls = g.event
            icon = {"generated": "🎯", "completed": "✓", "abandoned": "✗"}.get(g.event, "·")
            obj = _esc((g.objective or "")[:80])
            parts.append(f'<div class="goal {cls}">{icon} [{g.event}] {obj}</div>')

    if notepad_mgr:
        notepad = notepad_mgr.read(agent_id)
        if notepad.strip():
            parts.append("<h3>Notepad</h3>")
            parts.append(f'<div class="notepad">{_esc(notepad[:1000])}</div>')

    msgs = a2a_data.get(agent_id, [])
    if msgs:
        parts.append(f"<h3>A2A Messages ({len(msgs)})</h3>")
        for m in msgs[:10]:
            parts.append(
                f'<div class="msg">'
                f'<span class="from">{_esc(m.get("from_agent", "?"))}</span> → '
                f"{_esc(m.get('to_agent', '?'))} "
                f'<span class="type">[{_esc(m.get("type", "?"))}]</span> '
                f"{_esc((m.get('subject') or '')[:60])}"
                f"</div>"
            )

    parts.append("</div>")
    return "\n".join(parts)


def _load_a2a_data(hive_dir: Path | None) -> dict[str, list[dict[str, Any]]]:
    if not hive_dir:
        return {}
    a2a_dir = hive_dir / "a2a"
    if not a2a_dir.exists():
        return {}
    import json

    result: dict[str, list[dict[str, Any]]] = {}
    for agent_dir in a2a_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        inbox = agent_dir / "inbox.jsonl"
        if inbox.exists():
            msgs = []
            for line in inbox.read_text().strip().splitlines():
                try:
                    msgs.append(json.loads(line))
                except Exception:
                    continue
            if msgs:
                result[agent_dir.name] = msgs
    return result


def export_html_report(
    run_id: str,
    logs_dir: Path,
    output_path: Path,
    hive_dir: Path | None = None,
) -> Path:
    """Generate a standalone HTML report for a run."""
    reader = LogReader(logs_dir)
    summary = reader.get_summary(run_id)
    if not summary:
        raise ValueError(f"Run not found: {run_id}")

    notepad_mgr = NotepadManager(hive_dir) if hive_dir else None
    a2a_data = _load_a2a_data(hive_dir)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Hive Run {_esc(run_id)}</title>",
        f"<style>{CSS}</style></head><body>",
        "<h1>Hive Run Report</h1>",
        f'<p style="color:var(--dim)">Run: {_esc(run_id)} | '
        f"Started: {_esc(summary['started_at'])} | "
        f"Heartbeat: {summary['heartbeat']}s</p>",
    ]

    parts.append('<div class="stats">')
    for label, value in [
        ("Agents", summary["agents"]),
        ("Goals", summary["goals_generated"]),
        ("Completed", summary["goals_completed"]),
        ("Abandoned", summary["goals_abandoned"]),
        ("Tool Calls", summary["tool_calls"]),
        ("Tokens", f"{summary['total_tokens']:,}"),
        ("Cost", f"${summary['total_cost_usd']:.4f}"),
    ]:
        parts.append(
            f'<div class="stat"><div class="label">{label}</div>'
            f'<div class="value">{value}</div></div>'
        )
    parts.append("</div>")

    for aid in summary["agent_ids"]:
        parts.append(_build_agent_card(reader, run_id, aid, notepad_mgr, a2a_data))

    parts.append('<div class="footer">Generated by Hive Agent OS</div>')
    parts.append("</body></html>")

    html_content = "\n".join(parts)
    output_path.write_text(html_content)
    return output_path
