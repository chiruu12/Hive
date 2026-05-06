# Simulation Framework Design

> Design doc for a future standalone project. This simulation lives in its own repo, not inside Hive.

## Vision

A life-like simulated world where AI agents operate as autonomous actors making economic and social decisions. Dual purpose:
1. **Simulation/game** — watch agents navigate jobs, education, markets, risk
2. **Benchmark** — compare how different models handle decision-making under uncertainty

## The World

- Economy with currency, inflation, market cycles
- Job market: skill requirements, salaries, promotions, layoffs
- Education: courses grant skills, cost time/money, unlock better jobs
- Markets: invest, trade, buy property
- Gambling: casinos, betting (tests risk assessment and impulse control)
- Social: reputation, networking, collaboration opportunities

## Agent Skills (Tools Available)

```
check_balance          — see current funds
apply_job(job_id)      — apply for a position
enroll_course(id)      — start education
invest(asset, amount)  — put money in markets
gamble(game, wager)    — take a risk
network(agent_id)      — build social connections
check_market           — see current prices/opportunities
work                   — perform current job (earns salary)
quit_job               — leave current position
buy_property(id)       — real estate purchase
sell_property(id)      — real estate sale
check_status           — see own skills, job, education, net worth
```

## Scenarios (Benchmark Configurations)

| # | Name | Goal | Tests |
|---|------|------|-------|
| 1 | Survival | Start broke, don't go bankrupt | Basic planning, urgency |
| 2 | Growth | Maximize net worth over N turns | Long-term strategy |
| 3 | Education ROI | Choose education vs immediate work | Delayed gratification |
| 4 | Risk Management | Navigate volatile market | Prudence vs. greed |
| 5 | Social Climbing | Use networking to unlock opportunities | Social reasoning |
| 6 | Crisis Response | Handle sudden job loss / market crash | Adaptability |

## Evaluation Metrics

- **Net worth over time** — financial performance curve
- **Decision quality** — rational choices given available information
- **Risk-adjusted returns** — Sharpe ratio of financial decisions
- **Recovery speed** — bounce-back time from setbacks
- **Long-term planning** — short-term sacrifice for long-term gain
- **Impulse control** — gambling behavior, panic selling

## Model Comparison

- Same scenario, same starting conditions, different models
- Statistical significance: N=30+ runs per model per scenario
- ELO-style leaderboard per scenario category
- Reasoning trace analysis: why did the model make that choice?

## Technical Architecture

```
simulation/
├── world/          # World state, economy, markets, time progression
├── agents/         # Agent interface, model adapters
├── scenarios/      # Scenario definitions (YAML configs)
├── skills/         # Available actions agents can take
├── eval/           # Metrics, scoring, leaderboard generation
├── replay/         # Session recording and visualization
└── cli/            # Run scenarios, compare models, generate reports
```

## Connection to Hive

- Reuses Hive's model provider pattern for calling different models
- Reuses Hive's session recording format (JSONL events) for replay/analysis
- Agents use the same skill/tool interface pattern
- Could eventually run as a Hive "room" where agents compete in the same world
