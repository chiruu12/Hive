"""World interaction tools — query and act in the economy via context."""

from hive.execution.context import ExecutionContext
from hive.execution.protocol import ToolResult, tool


@tool("world_query", description="Query the world state", query_type="what to query")
async def world_query(
    agent_id: str, context: ExecutionContext | None = None, query_type: str = "status"
) -> ToolResult:
    """Query: my_status, available_jobs, market, skills."""
    if not context:
        return ToolResult(success=False, output="No context", error="no_context")
    w = context.world

    if query_type == "my_status":
        return ToolResult(success=True, output=w.get_status(agent_id))
    if query_type in ("available_jobs", "jobs"):
        jobs = w.available_jobs()
        if not jobs:
            return ToolResult(success=True, output="No jobs available.")
        lines = []
        for j in jobs:
            reqs = f" (requires: {', '.join(j.required_skills)})" if j.required_skills else ""
            lines.append(f"  {j.job_id}: {j.title} - ${j.salary}/cycle{reqs}")
        return ToolResult(success=True, output="Available jobs:\n" + "\n".join(lines))
    if query_type in ("market", "prices"):
        return ToolResult(success=True, output=w.get_market_summary())
    if query_type == "skills":
        skills = w.get_skills(agent_id)
        if not skills:
            return ToolResult(success=True, output="No skills learned yet.")
        lines = [f"  {s.skill_name}: {s.level:.0%}" for s in skills]
        return ToolResult(success=True, output="Your skills:\n" + "\n".join(lines))

    return ToolResult(
        success=True,
        output=f"Unknown query: {query_type}. Try: my_status, available_jobs, market, skills",
    )


@tool("world_action", description="Take an action in the world", action="what to do")
async def world_action(
    agent_id: str,
    context: ExecutionContext | None = None,
    action: str = "",
    target: str = "",
    amount: str = "",
) -> ToolResult:
    """Actions: work, apply_job, quit_job, learn, gamble."""
    if not context:
        return ToolResult(success=False, output="No context", error="no_context")
    w = context.world

    if not action:
        return ToolResult(
            success=False, output="No action. Try: work, apply_job, quit_job, learn, gamble"
        )
    if action == "work":
        result = w.work(agent_id)
        return ToolResult(success="Earned" in result, output=result)
    if action == "apply_job":
        if not target:
            return ToolResult(success=False, output="Specify job_id as target")
        result = w.apply_job(agent_id, target)
        return ToolResult(success="Hired" in result, output=result)
    if action == "quit_job":
        result = w.quit_job(agent_id)
        return ToolResult(success="Quit" in result, output=result)
    if action == "learn":
        if not target:
            return ToolResult(success=False, output="Specify skill name as target")
        result = w.learn(agent_id, target)
        return ToolResult(success="Studied" in result, output=result)
    if action == "gamble":
        wager = float(amount) if amount else 10.0
        game = target or "blackjack"
        result = w.gamble(agent_id, game, wager)
        return ToolResult(success=True, output=result.description)

    return ToolResult(success=False, output=f"Unknown action: {action}")
