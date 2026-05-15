"""Structured Output — get validated Pydantic models from agents.

Demonstrates two approaches:
1. run_structured() — full ReAct loop that returns a StructuredTaskResult
2. run_once_structured() — single-turn, returns the Pydantic model directly

Run: uv run python examples/03_structured_output.py
"""

import asyncio

from pydantic import BaseModel

from hive import Agent, Task, create_runtime_provider

# --- Output models ---


class CodeReview(BaseModel):
    """Structured code review output."""

    file: str
    issues: list[str]
    severity: str
    suggestion: str
    approved: bool


class MovieReview(BaseModel):
    """Compact movie review."""

    title: str
    year: int
    rating: float
    pros: list[str]
    cons: list[str]
    verdict: str


async def main() -> None:
    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(
        name="reviewer",
        model=provider,
        system_prompt="You are a senior code reviewer. Be thorough but concise.",
    )

    # --- Approach 1: run_structured (full task with ReAct loop) ---

    code_snippet = """
    def login(username, password):
        query = f"SELECT * FROM users WHERE name='{username}' AND pass='{password}'"
        result = db.execute(query)
        if result:
            return True
        return False
    """

    print("=== Approach 1: run_structured (Task-based) ===\n")

    result = await agent.run_structured(
        Task(instruction=f"Review this code for security issues:\n```python\n{code_snippet}\n```"),
        output_type=CodeReview,
    )

    print(f"Status: {result.status}")
    if result.parsed:
        review = result.parsed
        print(f"File: {review.file}")
        print(f"Severity: {review.severity}")
        print(f"Approved: {review.approved}")
        print("Issues:")
        for issue in review.issues:
            print(f"  - {issue}")
        print(f"Suggestion: {review.suggestion}")

    # --- Approach 2: run_once_structured (single turn, no tools) ---

    print("\n=== Approach 2: run_once_structured (one-shot) ===\n")

    critic = Agent(
        name="critic",
        model=provider,
        system_prompt="You are a film critic. Provide honest, balanced reviews.",
    )

    movie = await critic.run_once_structured(
        "Review the movie 'Inception' by Christopher Nolan",
        output_type=MovieReview,
    )

    print(f"Title: {movie.title} ({movie.year})")
    print(f"Rating: {movie.rating}/10")
    print(f"Pros: {', '.join(movie.pros)}")
    print(f"Cons: {', '.join(movie.cons)}")
    print(f"Verdict: {movie.verdict}")


if __name__ == "__main__":
    asyncio.run(main())
