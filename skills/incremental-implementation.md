Break large tasks into small, independently testable steps. Each step should:

1. Be completable in one cycle (< 20 tool calls)
2. Leave the codebase in a working state
3. Have a clear commit message describing what changed

If a task feels too big, split it:
- Extract the interface first, implement later
- Build a minimal version, then iterate
- Handle the common case first, edge cases in follow-up

Commit after each logical unit. Never leave uncommitted work.
