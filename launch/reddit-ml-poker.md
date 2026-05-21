# r/MachineLearning Post

**Title:** [P] Ran 5 poker tournaments with 6 LLMs (1.2B to 1T params). The smallest model won the most. Data inside.

---

Built a poker engine for LLMs and ran 5 Texas Hold'em tournaments. 6 models, identical poker persona, $1M buy-in, 25 hands per tournament. Sharing the results because the parameter-count-vs-performance relationship was not what I expected.

**Models tested:**

- Liquid lfm2.5 (1.2B, local)
- Qwen3 (1.7B, local)  
- Phi-4-mini (3.8B, local)
- Claude Haiku 4.5 (Anthropic)
- GPT-OSS (120B, Fireworks)
- MiniMax M2 (230B, Fireworks)
- Kimi K2 (~1T, Fireworks)

**Aggregate results (5 runs):**

| Model | Wins | Avg Place | Hand Win% | Raises | Folds | R/F Ratio | Avg Time |
|-------|------|-----------|-----------|--------|-------|-----------|----------|
| Liquid 1.2B | 2 | 1.6 | 61% | 53 | 9 | 5.89 | 5.6s |
| Qwen 1.7B | 1 | 2.2 | 70% | 53 | 9 | 5.89 | 147s |
| MiniMax 230B | 1 | 4.4 | 49% | 55 | 35 | 1.57 | 32s |
| Kimi 1T | 1 | 5.0 | 30% | 31 | 27 | 1.15 | 59s |
| GPT-OSS 120B | 0 | 3.3 | 8% | 11 | 17 | 0.65 | 16s |
| Haiku | 0 | 4.4 | 21% | 35 | 28 | 1.25 | 5.5s |

**Key observations:**

1. **Inverse correlation between model size and poker performance** in this format. The two smallest models (1.2B, 1.7B) have the best results. The two biggest (120B, 1T) have the worst.

2. **Raise/fold ratio is the strongest predictor of tournament success.** Liquid and Qwen both have R/F ratio of 5.89. GPT-OSS has 0.65. In a short tournament with high blinds, aggression beats precision.

3. **Haiku demonstrates the "optimal play paradox."** It plays GTO-adjacent poker -- folds marginal hands, raises strong ones. But in a field of opponents who don't respect ranges, GTO leaks value. Placed 4th-5th in all 5 runs.

4. **GPT-OSS Run 3 is the extreme case.** 0 raises, 5 folds in 6 hands. The 120B model correctly assessed hand strength and correctly folded weak hands. But correct folding in a format where blinds eat your stack is a losing strategy. Being right about hand strength while being wrong about strategy.

5. **Speed doesn't directly predict success,** but it correlates with decisiveness. Liquid (5.6s) and Haiku (5.5s) are similarly fast, but Liquid raises 6x more per fold. Speed enables aggression but doesn't cause it.

6. **Qwen has the highest hand win rate (70%)** but only 1 tournament win. It's selective and usually right -- but slower decision-making (147s avg) means it plays fewer hands before elimination in some runs.

**What this suggests:**

In constrained strategic environments (finite rounds, high cost of inaction), smaller models may outperform larger ones because they:
- Don't overthink marginal decisions
- Default to action when uncertain (raise > fold)
- Complete decisions faster, enabling more aggressive play cycles

This is likely format-dependent. In deeper tournaments (200+ hands, lower blinds), the larger models' superior hand reading should eventually dominate. We tested a format that penalizes inaction, which favors smaller models.

**Methodology:**

- Poker engine: pure Python, deterministic shuffling (seeded), correct side pot computation
- Each model gets identical system prompt with poker persona
- Prompt includes: hole cards, community, equity estimate (Monte Carlo, 500 sims), opponent stats, position, valid actions
- Response parsed as numbered choice (1-6)
- No fine-tuning, no poker-specific training -- raw model capability

All code and result JSONs are open source: https://github.com/chiruu12/Hive (`hive-arena/poker/`)

Built on Hive, a framework for running autonomous AI agents with persistent state and multi-model support.

**Reproducing:** If you want to run this with your own models, the poker engine is standalone Python with zero dependencies. The LLM integration uses Hive's agent SDK.

Interested in seeing results with Llama 3.1 70B, Mixtral 8x22B, or Command-R. Are bigger local models more like the aggressive small models or the cautious cloud models?
