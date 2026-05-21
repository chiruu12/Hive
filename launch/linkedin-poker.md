# LinkedIn Post

A 1.2B parameter model just beat a 1 trillion parameter model at poker.

I ran 5 Texas Hold'em tournaments with 6 LLMs -- ranging from 1.2B to 1T parameters. Local models vs cloud models. The results were counterintuitive.

The smallest model (Liquid, 1.2B, running locally on my MacBook) won 2 out of 5 tournaments. Best average placement across all runs.

The 120B model (GPT-OSS) never won a single tournament. In one run it had zero raises across 6 hands -- it understood the game well enough to know it had bad cards, but too well to bluff.

Claude Haiku placed 4th-5th in every single run. Textbook-correct poker -- fold bad hands, raise good ones. But in a short tournament, textbook loses against opponents who don't play by the book.

The winning strategy? Raise everything. Never fold.

Liquid's best run: 19 raises, 0 folds, $5.98M profit. Against models 100-800x its size.

Why this matters beyond poker:

In constrained competitive environments, smaller models can win by being decisive and fast -- not by being smarter. The big models overthink. They calculate risk correctly but act too slowly in a format that punishes inaction.

Speed of decision was ~5 seconds for the 1.2B model. The 1T model needed 60+ seconds. In fast-paced environments, that latency gap is lethal.

This isn't just a fun experiment. It's a real question for anyone deploying AI in competitive or time-sensitive contexts: is the biggest model always the right choice?

Built with Hive (https://github.com/chiruu12/Hive) -- an open source framework for running autonomous AI agents with persistent state, decision-making under pressure, and multi-model support.

If you have a local LLM setup, try running the tournament yourself. What would you optimize for -- speed or depth?

#AI #LLM #LocalAI #MachineLearning #OpenSource #DecisionMaking
