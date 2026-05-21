# r/MachineLearning

**Title:** [P] Ran 5 poker tournaments with 6 LLMs (1.2B to 1T). The 1.2B model won the most. Data and code inside.

---

Built a Texas Hold'em engine for LLMs and ran 5 tournaments. 6 models, identical persona prompt, $1M buy-in, 25 hands each. The parameter-count vs performance curve inverted.

**Models:** Liquid lfm2.5 (1.2B, local/LM Studio), Qwen3 (1.7B, local/LM Studio), Claude Haiku 4.5 (Anthropic), GPT-OSS (120B, Fireworks), MiniMax M2 (230B, Fireworks), Kimi K2 (~1T, Fireworks).

| Run | Winner | Size | Type |
|-----|--------|------|------|
| 1 | Qwen | 1.7B | local |
| 2 | MiniMax | 230B | cloud |
| 3 | Liquid | 1.2B | local |
| 4 | Kimi | ~1T | cloud |
| 5 | Liquid | 1.2B | local |

Liquid (1.2B) won 2/5. GPT-OSS (120B) and Haiku never won.

In Run 3, Liquid played 6 hands: 19 raises, 0 folds. GPT-OSS in the same run: 0 raises, 5 folds. The 120B model correctly assessed hand strength and correctly folded weak hands. Correct folding in a format where blinds and antes eat your stack each hand is a losing strategy. The small model didn't evaluate its hands at all, raised regardless, and won because nobody called.

**Limitations (important):** 25 hands with 5K/10K blinds + 1K ante is a high-pressure format. It punishes inaction and rewards aggression. The small models aren't "better at poker." They're exploiting a degenerate format where not-folding is the optimal deviation from standard play. In deeper tournaments (200+ hands, lower blinds), I'd expect the larger models' hand-reading to dominate. Haven't run those yet.

**Methodology:**
- Poker engine: pure Python, deterministic shuffle (seeded), correct side pot computation, full hand evaluation (all 10 ranks)
- Each model receives: hole cards, community cards, equity estimate (Monte Carlo, 500 sims), opponent stats (fold/raise rates), position, valid actions as numbered options
- Response parsed as numbered choice. Unparseable responses default to check/call.
- No fine-tuning or poker-specific training. Raw model capability only.
- Identical system prompt ("poker player") for all models

Looking for feedback on two things: (1) what tournament structure would better isolate LLM poker reasoning (deeper stacks? different blind structures?), and (2) what models should go in the next run. The framework supports custom personas per player (risk tolerance, personality traits, betting style) so if there are interesting persona configurations to test strategic divergence, I'll run them.

Code and all result JSONs: https://github.com/chiruu12/Hive (`hive-arena/` for the tournament runner, `tournaments/results/` for raw data)
