# LinkedIn

I made 6 AI models play poker. The smallest one won the most.

The lineup: 1.2B, 1.7B, Claude Haiku, 120B, 230B, and a ~1T model. Mix of local (running on my 16GB MacBook) and cloud. Texas Hold'em, $1M buy-in, identical prompts, 5 tournaments.

The 1.2B model (Liquid lfm2.5) won 2 out of 5. In one tournament it made 19 raises and 0 folds across 6 hands. Pure aggression, zero strategy.

The 120B model (GPT-OSS) never won. In one run: 0 raises, 5 folds. It understood the game well enough to know it had bad cards. In a short tournament, folding bleeds you dry. It was right about every hand and lost anyway.

Caveat: 25 hands with high blinds favors aggression over strategy. The small model isn't smarter. It wins because it doesn't overthink.

There's something worth noting though. In constrained environments where inaction has a cost, the model that acts fast and decisively often beats the model that reasons deepest. The 1.2B decided in 5 seconds. The 1T took 60. When the format punishes waiting, that speed gap compounds.

Next up: longer tournaments with community-submitted models and custom player personas. If you have a model or player archetype you'd want to see at the table, I'm collecting suggestions.

Code and results: https://github.com/chiruu12/Hive

#AI #LLM #LocalAI #MachineLearning #OpenSource #DecisionMaking
