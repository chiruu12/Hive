# r/LocalLLaMA Post

**Title:** A 1.2B local model just beat Claude Haiku, a 1T model, and a 120B model at poker. Ran 5 tournaments on a 16GB Mac.

---

I built a poker engine that lets LLMs play Texas Hold'em against each other. Ran 5 full tournaments with 6 models -- 3 local (via LM Studio) and 3 cloud. The results surprised me.

**The lineup:**

| Model | Size | Type | Speed/decision |
|-------|------|------|---------------|
| Liquid lfm2.5 | 1.2B | local | ~5s |
| Qwen3 | 1.7B | local | ~2.5min |
| Phi-4-mini | 3.8B | local | ~7min |
| Claude Haiku 4.5 | -- | cloud | ~5s |
| GPT-OSS | 120B | cloud | ~16s |
| MiniMax M2 | 230B | cloud | ~32s |
| Kimi K2 | ~1T | cloud | ~60s |


**Results across 5 runs:**

Liquid (1.2B) won 2 tournaments. Best average placement at 1.6. The 1.2B model running on my MacBook beat models up to 800x its size.

GPT-OSS (120B) never won a single tournament. In Run 3 it had 0 raises and 5 folds across 6 hands -- it was too smart to bluff and just bled chips to the blinds.

Haiku placed 4th-5th in all 5 runs. The best player who never wins. It plays textbook poker -- folds bad hands, raises strong ones -- but textbook poker loses when your opponents don't understand poker theory well enough to be predictable.

**The standout: Liquid's Run 3**

19 raises. 0 folds. Never folded a single hand in the entire tournament. Pure fearless aggression. Won $5.98M from a starting stack of $1M. Against a 120B model that folded 5 times without raising once.

**Why small models win at poker:**

The big models "understand" poker too well. They know K-3 offsuit is bad and fold it. But in a 25-hand tournament with 5K/10K blinds and 1K ante, folding bleeds you dry. Liquid doesn't know what a bad hand looks like, so it raises everything. Against opponents who fold too much, that prints money.

The dumbest strategy -- raise everything, never fold -- was the winningest strategy. Small models' lack of understanding is their competitive advantage.

**Setup if you want to try:**

Everything runs locally. The poker engine is pure Python, zero deps. The tournament runner uses our framework Hive for the LLM integration.

```
pip install hive-agent
```

Repo: https://github.com/chiruu12/Hive (poker engine + arena in `hive-arena/`)

I ran this on a 16GB M-series Mac. Only had enough RAM for one local model at a time, so the local models played sequentially. If you have 32GB+ you could run all 3 local models simultaneously.

Would love to see results with different local models -- especially curious if Mistral 7B or Llama 3.1 8B play differently. Do bigger local models fold more like the cloud models, or stay aggressive like Liquid?

**TL;DR:** 1.2B model beat 1T model at poker because it's too dumb to fold. Sometimes ignorance is bliss.
