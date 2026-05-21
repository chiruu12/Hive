# r/MachineLearning Post

**Title:** [P] Hive: Multi-agent framework with a suffering system that mechanically changes agent behavior -- watching how different LLMs handle pressure

---

I built a framework for running persistent autonomous agents and I've been using it to observe how different models behave under identical conditions.

**The setup:** Agents have a Persona (personality traits, values, fears, goals) and exist in a simulated world with jobs, money, and random life events. They generate their own goals each cycle based on their current state. The key mechanic is a suffering system -- six stressor types (futility, invisibility, repeated failure, purposelessness, identity violation, existential threat) that escalate over time and *mechanically* modify the agent's behavioral parameters.

This isn't prompt engineering. When an agent's futility score crosses 0.5, their `risk_tolerance` parameter increases by 0.1 per cycle. When invisibility is high, their `social_drive` increases -- they send more messages, write more in their journal. In crisis mode (cumulative load > 0.9), risk tolerance jumps to 0.9 and concentration drops to 0.3. The agent's goal generation, tool usage, and decision-making all shift measurably.

**What I've been observing:**

Running the same scenario (3 agents, 50 cycles, economy enabled) across different models produces noticeably different behavioral patterns:

- Smaller models (Haiku, local Llama) tend to generate simpler, more conservative goals and recover from suffering faster (fewer complex goals = fewer failures = less futility)
- Larger models (Sonnet, GPT-4o) generate more ambitious goals, fail more often, and develop more complex suffering trajectories
- The journal entries diverge wildly -- some models write mechanically, others produce genuinely interesting reflections about their situation

**Built-in comparison tool:**

```
hive benchmark survival --models anthropic:lite,openai:lite,ollama:standard
```

Runs the same scenario per model and compares: goal completion rate, suffering trajectory, cost, journal quality.

**Framework details:**
- Agents keep persistent journals (notepad, tool requests, evolution notes)
- A2A typed protocol for inter-agent communication (request/response/review/delegate)
- Sub-agent spawning with parent-child lifecycle
- Config-driven YAML profiles with full Persona definition
- Multi-provider: Anthropic, OpenAI, Groq, Fireworks, Ollama, LM Studio

11K LOC Python, 554 tests, MIT licensed. Not an enterprise orchestrator -- this is for running experiments on multi-agent behavior.

https://github.com/chiruu12/Hive

The suffering→behavior coupling is what I'm most interested in feedback on. The current mapping (futility → risk, invisibility → social seeking, etc.) is hand-designed. Curious if anyone has pointers to literature on computational models of stress response that could inform better mappings.
