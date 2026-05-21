# Show HN: Hive – AI agents that suffer, keep journals, and live in a simulated economy

I built an agent framework where agents aren't just stateless function calls -- they're persistent entities with an inner life.

Each agent has a Persona: personality traits, values, fears, long-term goals. They generate their own goals autonomously based on their current state. They experience suffering (6 types: futility, invisibility, purposelessness, repeated failure, identity violation, existential threat) that mechanically changes their behavior -- a suffering agent takes bigger risks, writes more in its journal, or goes completely off-script. They work jobs, earn money, learn skills, and make life decisions when random events hit them.

The interesting part is watching what happens. Run `hive demo survival` and three agents spawn: a methodical coder, a reckless gambler, and a contemplative philosopher. Within 90 seconds the gambler has lost half their money at blackjack, the philosopher is ignoring work to write journal entries about the meaning of purpose, and the coder is quietly suffering from invisibility because nobody reads their output. Suffering bars diverge. Happiness shifts. Journal entries get more desperate or more philosophical. It's like watching a tiny ant farm where each ant has a therapist.

Built it because I wanted agents that feel like characters, not tools. Multi-model support (Claude, GPT, Groq, Fireworks, Ollama, LM Studio), config-driven YAML profiles, A2A messaging protocol, sub-agent spawning, scheduled goals, web browsing. The SDK side is clean -- `from hive import Agent, Persona` and you're building. The simulation side is where it gets weird.

Local-first, MIT licensed, runs on your machine. No cloud dependency.

GitHub: https://github.com/chiruu12/Hive

Happy to answer questions about the suffering system design or how agents actually behave differently under pressure.
