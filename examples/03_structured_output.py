"""Structured Output — get validated Pydantic models from agents.

Run: uv run python examples/03_structured_output.py
"""

import asyncio

from pydantic import BaseModel

from hive import Agent, Task, create_runtime_provider


class CodeReview(BaseModel):
    """Structured code review output."""
    file: str
    issues: list[str]
    severity: str  # "low", "medium", "high", "critical"
    suggestion: str
    approved: bool


async def main() -> None:
    provider = create_runtime_provider("claude-haiku-4-5")

    agent = Agent(
        name="reviewer",
        model=provider,
        system_prompt="You are a senior code reviewer.",
    )

    code_snippet = '''
    def login(username, password):
        query = f"SELECT * FROM users WHERE name='{username}' AND pass='{password}'"
        result = db.execute(query)
        if result:
            return True
        return False
    '''

    result = await agent.run_structured(
        Task(instruction=f"Review this code for security issues:\n```python\n{code_snippet}\n```"),
        output_type=CodeReview,
    )

    print(f"Status: {result.status}")
    if result.parsed:
        review = result.parsed
        print(f"\nFile: {review.file}")
        print(f"Severity: {review.severity}")
        print(f"Approved: {review.approved}")
        print(f"Issues:")
        for issue in review.issues:
            print(f"  - {issue}")
        print(f"Suggestion: {review.suggestion}")


if __name__ == "__main__":
    asyncio.run(main())
