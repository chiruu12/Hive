"""Self-contained control-plane web UI served at ``/``.

A single static page (no build step, no dependencies) that talks to the REST API
in this same process. Read-only views of agents, sessions, and goals, plus the
pending-approval queue with approve/deny actions -- the browser-based control plane.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hive AgentOS</title>
<style>
  :root { --bg:#0d1117; --panel:#161b22; --border:#30363d; --fg:#e6edf3; --dim:#8b949e;
          --accent:#58a6ff; --green:#3fb950; --yellow:#d29922; --magenta:#bc8cff; --red:#f85149; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 -apple-system,
         BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  header { display:flex; align-items:center; gap:16px; padding:14px 20px;
           border-bottom:1px solid var(--border); background:var(--panel); position:sticky; top:0; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  header h1 span { color:var(--accent); }
  header .meta { margin-left:auto; color:var(--dim); font-size:12px; display:flex; gap:12px; align-items:center; }
  input { background:var(--bg); border:1px solid var(--border); color:var(--fg);
          border-radius:6px; padding:4px 8px; font:inherit; }
  main { padding:20px; max-width:1100px; margin:0 auto; }
  section { background:var(--panel); border:1px solid var(--border); border-radius:8px;
            margin-bottom:20px; overflow:hidden; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--dim);
       margin:0; padding:12px 16px; border-bottom:1px solid var(--border); }
  table { width:100%; border-collapse:collapse; }
  td, th { text-align:left; padding:9px 16px; border-bottom:1px solid var(--border); font-size:13px; }
  th { color:var(--dim); font-weight:500; }
  tr:last-child td { border-bottom:none; }
  .empty { padding:16px; color:var(--dim); font-style:italic; }
  .badge { padding:2px 8px; border-radius:10px; font-size:11px; font-weight:600; }
  .idle { color:var(--dim); } .working { color:var(--yellow); }
  .waiting_approval { color:var(--magenta); } .error,.dead { color:var(--red); }
  code { background:var(--bg); padding:1px 5px; border-radius:4px; color:var(--dim); font-size:12px; }
  button { background:var(--accent); color:#fff; border:none; border-radius:6px; padding:4px 12px;
           font:inherit; cursor:pointer; }
  button.deny { background:var(--red); }
  button:hover { opacity:.9; }
</style>
</head>
<body>
<header>
  <h1>Hive <span>AgentOS</span></h1>
  <div class="meta">
    <label>user <input id="user" value="default" size="8"></label>
    <span id="clock">--</span>
  </div>
</header>
<main>
  <section><h2>Pending Approvals</h2><div id="approvals"></div></section>
  <section><h2>Agents</h2><div id="agents"></div></section>
  <section><h2>Sessions</h2><div id="sessions"></div></section>
</main>
<script>
const $ = id => document.getElementById(id);
const userHdr = () => ({ "X-Hive-User": $("user").value || "default" });
// Escape for HTML text AND attribute contexts (includes quotes), so untrusted
// fields (ids, status, args) can't break out of an attribute or inject markup.
const ESC = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ESC[c]);

async function api(path, opts = {}) {
  // Merge headers so a caller-supplied `headers` can't drop X-Hive-User.
  const { headers, ...rest } = opts;
  const r = await fetch(path, { headers: { ...userHdr(), ...headers }, ...rest });
  if (!r.ok) throw new Error(r.status + " " + path);
  return r.status === 204 ? null : r.json();
}

function table(rows, cols) {
  if (!rows.length) return '<div class="empty">none</div>';
  const head = "<tr>" + cols.map(c => "<th>" + c.h + "</th>").join("") + "</tr>";
  const body = rows.map(r => "<tr>" + cols.map(c => "<td>" + c.f(r) + "</td>").join("") + "</tr>").join("");
  return "<table>" + head + body + "</table>";
}

async function decide(agentId, approvalId, decision) {
  try {
    await api(`/agents/${encodeURIComponent(agentId)}/approvals/${encodeURIComponent(approvalId)}`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }) });
    refresh();
  } catch (e) { alert("Failed: " + e.message); }
}

// Delegated click handler: ids come from dataset (never from interpolated markup).
$("approvals").addEventListener("click", e => {
  const btn = e.target.closest("button.act");
  if (btn) decide(btn.dataset.agent, btn.dataset.id, btn.dataset.decision);
});

async function refresh() {
  try {
    const [agents, approvals, sessions] = await Promise.all([
      api("/agents"), api("/approvals"), api("/sessions"),
    ]);
    $("agents").innerHTML = table(agents, [
      { h: "Name", f: a => esc(a.name) },
      { h: "Role", f: a => esc(a.role) },
      { h: "Model", f: a => "<code>" + esc(a.model) + "</code>" },
      { h: "Status", f: a => `<span class="badge ${esc(a.status)}">${esc(a.status)}</span>` },
      { h: "Goal", f: a => esc(a.goal) || "<span class='empty'>-</span>" },
    ]);
    // Buttons carry ids in escaped data-* attributes; a single delegated listener
    // (below) handles clicks, so no untrusted value is ever interpolated into JS.
    $("approvals").innerHTML = table(approvals, [
      { h: "Tool", f: a => "<code>" + esc(a.tool_name) + "</code>" },
      { h: "Agent", f: a => esc(a.agent_id) },
      { h: "Arguments", f: a => "<code>" + esc((a.arguments || "").slice(0, 80)) + "</code>" },
      { h: "", f: a => {
          const attrs = `data-agent="${esc(a.agent_id)}" data-id="${esc(a.approval_id)}"`;
          return `<button class="act" data-decision="approve" ${attrs}>Approve</button>
                  <button class="act deny" data-decision="deny" ${attrs}>Deny</button>`;
      } },
    ]);
    $("sessions").innerHTML = table(sessions, [
      { h: "Session", f: s => "<code>" + esc(s.session_id) + "</code>" },
      { h: "Agent", f: s => esc(s.agent_id) },
      { h: "Status", f: s => esc(s.status) },
      { h: "Task", f: s => esc((s.task || "").slice(0, 60)) },
    ]);
    $("clock").textContent = new Date().toLocaleTimeString();
  } catch (e) { $("clock").textContent = "error: " + e.message; }
}

$("user").addEventListener("change", refresh);
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def control_plane() -> str:
    """Serve the browser control plane."""
    return _HTML
