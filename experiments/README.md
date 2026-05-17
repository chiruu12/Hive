# Hive Experiments

Pre-launch experiments to collect real data, screenshots, and stories.

## Setup

```bash
cd /path/to/Hive
uv sync
export ANTHROPIC_API_KEY=sk-ant-...
```

## Running Experiments

Each experiment is a standalone script:

```bash
python experiments/scripts/exp_model_compare.py
python experiments/scripts/exp_suffering_trajectories.py
python experiments/scripts/exp_economy_dynamics.py
python experiments/scripts/exp_journal_quality.py
python experiments/scripts/exp_personality_clash.py
python experiments/scripts/exp_survival_marathon.py
```

## What Each Experiment Tests

| Experiment | Question | Agents | Cycles |
|------------|----------|--------|--------|
| Model Compare | Do different models produce different personalities? | 3 (identical config, different models) | 50 |
| Suffering Trajectories | How do profiles develop suffering differently? | 5 (coder, gambler, philosopher, hustler, reviewer) | 100 |
| Economy Dynamics | Which personalities make money? | 5 (mixed profiles) | 100 |
| Journal Quality | What do agents actually write? | 3 (journal preset) | 50 |
| Personality Clash | What happens when opposites interact? | 2 (hustler + philosopher) | 30 |
| Survival Marathon | Long-run lifecycle patterns? | 3 (coder, gambler, philosopher) | 200 |

## Output

- `results/` — Raw JSON metrics (gitignored, regenerate by re-running)
- `reports/` — HTML reports (gitignored)
- `screenshots/` — Curated TUI screenshots for launch posts (committed)

## TUI Screenshots

Run with the `--screenshot` flag during experiments:

```bash
hive watch --screenshot experiments/screenshots/ --screenshot-interval 10
```

This saves Rich console exports every 10 seconds for later curation.
