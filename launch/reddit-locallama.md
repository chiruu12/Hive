# r/LocalLLaMA Post

**Title:** I made an "ant farm" for local LLMs -- agents run on Ollama/LM Studio, keep journals, experience suffering, and live in a simulated economy

---

Been working on this for a few weeks. It's called Hive.

The pitch: you spawn AI agents locally and watch them live. Not "execute a task and exit" -- they persist, generate their own goals, write in journals, suffer when things go wrong, earn money at jobs, make life decisions. Think Dwarf Fortress but the dwarves are language models.

**Local-first is the point.** Ollama and LM Studio are auto-detected. No API key needed to get started. You can mix models -- run Llama for routine tasks, Claude for planning if you want, or keep everything local. The model router picks cheap models for simple stuff and expensive ones for hard stuff.

Quick start:

```
pip install hive-agent
hive init
hive demo survival
```

That spawns three agents with different personalities -- a risk-averse coder, a reckless gambler, and a philosopher who ignores work to journal. You watch them for 90 seconds in a terminal dashboard. The gambler loses money. The philosopher writes about the meaning of purpose while their suffering bar climbs. The coder quietly does their job but starts getting desperate when nobody notices.

Suffering isn't cosmetic. When an agent's futility score gets high enough, their risk tolerance actually increases in the code. They start making different decisions. A suffering agent might gamble, go off-script, or spam messages to other agents. It's not just a prompt change -- the behavioral parameters shift.

**What it is:** A framework for running persistent multi-agent simulations locally. Config-driven YAML profiles for agents. Built-in economy, A2A messaging, sub-agent spawning, scheduled goals.

**What it isn't:** Not trying to compete with AutoGen or CrewAI. Those are workflow orchestrators for production use. This is closer to a research tool / entertainment piece. I built it because I wanted to watch LLMs make life decisions under pressure.

Works with: Ollama (any model), LM Studio, Claude, GPT, Groq, Fireworks. All via tier presets -- `Ollama.standard()` or `Anthropic.lite()`.

MIT licensed. ~11K LOC Python. 554 tests passing.

https://github.com/chiruu12/Hive

Would love to hear what models produce the most interesting behavior. I've been running it with llama3.1 locally and the agents are... cautious. Wondering if smaller models produce wilder results.
