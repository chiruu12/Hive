# r/LocalLLaMA

**Title:** My 1.2B model won 2 out of 5 poker tournaments against models up to 1T params. It never folded once.

---

I made 6 LLMs play Texas Hold'em against each other. Ran 5 tournaments on my 16GB MacBook. The 1.2B local model won more than anything else.

| Run | Winner | Size |
|-----|--------|------|
| 1 | Qwen | 1.7B local |
| 2 | MiniMax | 230B cloud |
| 3 | **Liquid** | **1.2B local** |
| 4 | Kimi | ~1T cloud |
| 5 | **Liquid** | **1.2B local** |

Lineup was Liquid lfm2.5 (1.2B, LM Studio, ~5s/decision), Qwen3 (1.7B, LM Studio, ~2.5 min), Claude Haiku 4.5, GPT-OSS (120B, Fireworks), MiniMax M2 (230B, Fireworks), and Kimi K2 (~1T, Fireworks).

Run 3 was wild. Liquid played 6 hands: 19 raises, 0 folds. Just raised everything no matter what cards it had. Won $5.98M from a $1M starting stack. GPT-OSS (120B) in the same run did 0 raises and 5 folds in 6 hands. The 120B model was too smart to bluff and it got blinded out.

Before you come for me: yes, 25 hands with 5K/10K blinds + 1K ante is basically a shove-or-fold format. This is not deep poker. The format punishes patience and rewards aggression. The big models "understand" poker well enough to fold bad hands. Folding bleeds you dry when blinds eat your stack every round.

Liquid doesn't know what a bad hand looks like. So it raises everything. Against opponents who fold too much, that prints money. Not claiming small models are smarter at poker. I'm saying in this specific format, not knowing when to fold is an advantage. Which is kind of hilarious.

I want to run longer tournaments (100+ hands, lower blinds) where hand-reading actually matters. If you have a local model you want to see at the table, drop it below. Especially curious about Mistral 7B, Llama 3.1 8B, Gemma 2 9B. The framework also supports custom personas (personality traits, risk tolerance, fears) per player, so if you want to design a degenerate gambler or a paranoid folder, I'll build it and run it.

Side note: my fan was screaming during the Phi-4 runs. Seven minutes per decision. It played 2 hands before getting eliminated. Only had enough RAM for one local model at a time so the locals played sequentially. If you have 32GB+ and want to run 3 local models simultaneously, the tournament runner supports `--mode simultaneous`.

Code and full result JSONs: https://github.com/chiruu12/Hive (tournament runner is in `hive-arena/`, results in `tournaments/results/`)
