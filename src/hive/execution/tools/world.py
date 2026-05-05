"""World interaction tools — query and act in the simulated world."""

from hive.execution.protocol import ToolResult, tool


@tool("world_query", description="Query the world state", query_type="what to query")
async def world_query(agent_id: str, query_type: str = "status") -> ToolResult:
    """Query world state: available_jobs, other_agents, my_status, prices."""
    responses = {
        "available_jobs": (
            "Available positions:\n"
            "  - Data Analyst ($50/cycle, requires: analysis)\n"
            "  - Code Reviewer ($70/cycle, requires: code_review)\n"
            "  - Researcher ($40/cycle, requires: none)\n"
            "  - Teacher ($60/cycle, requires: teaching)"
        ),
        "other_agents": "Query the daemon for peer information.",
        "my_status": f"Agent {agent_id}: active, balance unknown (economy not yet live)",
        "prices": (
            "Market prices:\n"
            "  - Skill course: $100\n"
            "  - Lottery ticket: $10 (1 in 50 chance of $200)\n"
            "  - Premium tools: $150"
        ),
    }
    output = responses.get(query_type, f"Unknown query type: {query_type}")
    return ToolResult(success=True, output=output)


@tool("world_action", description="Take an action in the world", action="what to do")
async def world_action(agent_id: str, action: str = "", target: str = "") -> ToolResult:
    """Take world action: apply_job, work, learn, gamble, buy, sell."""
    if not action:
        return ToolResult(success=False, output="No action specified", error="missing_action")

    if action == "work":
        return ToolResult(success=True, output=f"Agent {agent_id} completed a work cycle. +$50")
    if action == "learn":
        return ToolResult(
            success=True, output=f"Agent {agent_id} studied '{target}'. Skill progress +10%"
        )
    if action == "gamble":
        return ToolResult(
            success=True, output=f"Agent {agent_id} gambled on '{target}'. Lost $10. House wins."
        )
    if action == "apply_job":
        return ToolResult(
            success=True, output=f"Agent {agent_id} applied for '{target}'. Application pending."
        )

    return ToolResult(success=False, output=f"Unknown action: {action}", error="unknown_action")
