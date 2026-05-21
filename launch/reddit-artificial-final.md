# r/artificial

**Title:** I made 6 AI models play poker against each other. The 1.2B model has a gambling problem and it keeps winning.

---

Made LLMs play Texas Hold'em against each other. 6 models at the table: a tiny 1.2B running on my MacBook, a couple mid-size ones, and cloud models going up to about 1 trillion parameters.

Ran 5 tournaments. The tiny model won twice. More than any other model.

Its strategy? Raise everything. Never fold. It played one tournament with 19 raises and 0 folds across 6 hands. It didn't know it had bad cards. It just kept shoving chips in.

The 120B model played the same tournament with 0 raises and 5 folds. It understood the game perfectly. Knew exactly when it had bad cards. And folded itself into elimination.

The small model won because it was too dumb to be scared.

There's a real lesson about overthinking vs just doing the thing buried in there somewhere. Mostly it's just funny to watch AI models develop what looks like a gambling addiction.

The system also supports custom personas. You can give a model personality traits, fears, risk tolerance. "Reckless gambler who chases losses" plays completely different from "cautious philosopher who only bets on sure things."

I want to run a community tournament next. Tell me what model should play (any API or local model), what persona it should have (personality traits, risk level, fears), and what format (short and aggressive? long and deep? heads-up death match?). I'll run it and post the full play-by-play.

Results and code: https://github.com/chiruu12/Hive (check `hive-arena/` and `tournaments/results/`)
