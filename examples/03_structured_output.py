"""Structured Output — get validated Pydantic models from agents.

Demonstrates two approaches:
1. run_structured() — full ReAct loop that returns a StructuredTaskResult
2. run_once_structured() — single-turn, returns the Pydantic model directly

Run: uv run python examples/03_structured_output.py
"""

import asyncio

from pydantic import BaseModel

from hive import Agent, Instructions, Task
from hive.models.anthropic import Anthropic


class CodeReview(BaseModel):
    file: str
    issues: list[str]
    severity: str
    suggestion: str
    approved: bool


class MovieReview(BaseModel):
    title: str
    year: int
    rating: float
    pros: list[str]
    cons: list[str]
    verdict: str


async def main() -> None:
    # --- Approach 1: run_structured with response_model on Agent ---

    reviewer = Agent(
        name="reviewer",
        model=Anthropic.lite(),
        instructions=Instructions(
            persona="a senior code reviewer",
            instructions=["Be thorough but concise", "Focus on security issues"],
        ),
        response_model=CodeReview,
    )

    code_snippet = """
    def login(username, password):
        query = f"SELECT * FROM users WHERE name='{username}' AND pass='{password}'"
        result = db.execute(query)
        if result:
            return True
        return False
    """

    print("=== Approach 1: run_structured (Task-based) ===\n")

    result = await reviewer.run_structured(
        Task(instruction=f"Review this code:\n```python\n{code_snippet}\n```"),
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

    # --- Approach 2: run_once_structured (single turn, no tools) ---

    print("\n=== Approach 2: run_once_structured (one-shot) ===\n")

    critic = Agent(
        name="critic",
        model=Anthropic.lite(),
        instructions=Instructions(
            persona="a film critic",
            instructions=["Provide honest, balanced reviews"],
        ),
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
