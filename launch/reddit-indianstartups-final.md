# r/IndianStartups / r/developersIndia

**Title:** I made 6 AI models play poker against each other. The 1.2B model running on my MacBook won the most.

---

Made LLMs play Texas Hold'em against each other. 6 models at the table: a tiny 1.2B running locally on my 16GB MacBook, a couple mid-size ones, and cloud models going up to about 1 trillion parameters.

Ran 5 tournaments. The tiny model won twice. More than any other model at the table.

Its strategy? Raise everything. Never fold. One tournament it played 6 hands with 19 raises and 0 folds. Didn't even know it had bad cards. Just kept shoving chips in.

The 120B model in the same tournament? 0 raises, 5 folds. Understood the game perfectly. Knew when it had weak hands. And folded itself into elimination.

The small model won because it was too dumb to be scared.

Now before the poker bros come for me: 25 hands with high blinds is not deep poker. The format punishes patience and rewards aggression. The big models fold correctly by poker theory, but correct folding bleeds you dry when blinds eat your stack every round. So no, small models aren't "smarter." They just happen to be accidentally perfect for this format.

Built the whole thing from scratch. The poker engine is pure Python, zero dependencies. Hand evaluation, side pots, equity calculator, everything. The LLM layer runs on top of an agent framework I've been building called Hive. Supports LM Studio, Ollama, Anthropic, OpenAI, Fireworks, Groq. Also has a persona system where you can give models personality traits, risk tolerance, fears. A reckless gambler plays completely different from a cautious analyst.

Planning to run more of these. Community tournament maybe. If you have a model you want to see at the table, or a persona you want me to test ("aggressive bluffer who tilts after losses" or "tight grinder who only plays premium hands"), let me know. I'll run it and post full results.

Also genuinely looking for feedback on the framework and engine code if anyone wants to take a look. Still early but the core is solid. 554 tests passing, runs on a Mac.

Code, engine, and all 5 tournament results: https://github.com/chiruu12/Hive (poker stuff is in `hive-arena/`, results in `tournaments/results/`)
