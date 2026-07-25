"""Structured Extraction — extract structured data from unstructured text.

Demonstrates `run_structured` and `run_once_structured` with Pydantic
models to extract structured information from free-form text.

Run: uv run python examples/26_structured_extraction.py
"""

import asyncio

from pydantic import BaseModel, Field

from hive import Agent, Instructions, Task
from hive.models.anthropic import Anthropic

# --- Define extraction schemas ---


class ContactInfo(BaseModel):
    """Extracted contact information."""

    name: str = Field(description="Full name of the person")
    email: str = Field(default="", description="Email address if mentioned")
    phone: str = Field(default="", description="Phone number if mentioned")
    company: str = Field(default="", description="Company or organization")
    role: str = Field(default="", description="Job title or role")


class MeetingNotes(BaseModel):
    """Structured meeting notes."""

    title: str = Field(description="Meeting title or topic")
    date: str = Field(default="", description="Date if mentioned")
    attendees: list[str] = Field(default_factory=list, description="List of attendee names")
    decisions: list[str] = Field(default_factory=list, description="Decisions made")
    action_items: list[str] = Field(default_factory=list, description="Action items with owners")
    next_steps: str = Field(default="", description="Next steps or follow-up")


class BugReport(BaseModel):
    """Structured bug report."""

    title: str = Field(description="Short bug title")
    severity: str = Field(description="critical, high, medium, or low")
    steps_to_reproduce: list[str] = Field(default_factory=list)
    expected_behavior: str = Field(description="What should happen")
    actual_behavior: str = Field(description="What actually happens")
    environment: str = Field(default="", description="OS, browser, version info")
    workaround: str = Field(default="", description="Known workaround if any")


async def main() -> None:
    provider = Anthropic.lite()
    agent = Agent(
        name="extractor",
        model=provider,
        instructions=Instructions(
            persona="a precise data extraction specialist",
            instructions=[
                "Extract structured information accurately",
                "Use empty strings for missing information",
                "Be thorough but don't invent data",
            ],
        ),
    )

    # Example 1: Extract contact info
    print("=== Contact Extraction ===\n")
    contact_text = """
    Hey team, I met with Sarah Chen from Acme Corp today. She's their VP of
    Engineering and will be our main point of contact for the integration project.
    Her email is sarah.chen@acme.com and you can reach her at (555) 123-4567.
    She mentioned that their tech lead, James Park, will handle the API side.
    """

    result_contact = await agent.run_structured(
        Task(instruction=f"Extract contact information from this text:\n\n{contact_text}"),
        output_type=ContactInfo,
    )
    contact = result_contact.parsed
    print(f"Name: {contact.name}")
    print(f"Email: {contact.email}")
    print(f"Phone: {contact.phone}")
    print(f"Company: {contact.company}")
    print(f"Role: {contact.role}")

    # Example 2: Extract meeting notes
    print("\n=== Meeting Notes Extraction ===\n")
    meeting_text = """
    Sprint Planning - Jan 15, 2025

    Attendees: Alice, Bob, Charlie, Diana

    We decided to go with PostgreSQL for the new service instead of MongoDB.
    The migration will happen in two phases: first the read path, then writes.

    Action items:
    - Alice: Set up the PostgreSQL cluster by Friday
    - Bob: Write the migration scripts for the user table
    - Charlie: Update the API documentation
    - Diana: Schedule the stakeholder review for next Tuesday

    Next sprint planning is on Jan 29.
    """

    result_notes = await agent.run_structured(
        Task(instruction=f"Extract structured meeting notes:\n\n{meeting_text}"),
        output_type=MeetingNotes,
    )
    notes = result_notes.parsed
    print(f"Title: {notes.title}")
    print(f"Attendees: {notes.attendees}")
    print(f"Decisions: {notes.decisions}")
    print(f"Action items: {notes.action_items}")
    print(f"Next steps: {notes.next_steps}")

    # Example 3: One-shot structured extraction (no conversation history)
    print("\n=== One-Shot Bug Report Extraction ===\n")
    bug_text = """
    The login page crashes on Safari when using SSO. Users see a white screen
    after clicking the SSO button. Happens every time on Safari 17.2 on macOS
    Sonoma. Works fine on Chrome and Firefox. The console shows a
    TypeError about undefined property 'redirectUrl'. For now users can
    use email/password login instead.
    """

    bug = await agent.run_once_structured(
        f"Extract a structured bug report from this description:\n\n{bug_text}",
        output_type=BugReport,
    )
    print(f"Title: {bug.title}")
    print(f"Severity: {bug.severity}")
    print(f"Steps: {bug.steps_to_reproduce}")
    print(f"Expected: {bug.expected_behavior}")
    print(f"Actual: {bug.actual_behavior}")
    print(f"Environment: {bug.environment}")
    print(f"Workaround: {bug.workaround}")


if __name__ == "__main__":
    asyncio.run(main())
