# Stabilization Phase 6 -- CI and soak gate

## Problem statement

Measured health baselines are not encoded in CI thresholds. A green local run today does not prevent tomorrow's drift. Adversarial suite has one intermittent test. Coverage and job boundaries need explicit policy after Phases 0--5 land.

### Exact files and functions

| Area | Location | Current state |
|------|----------|---------------|
| CI workflow | `.github/workflows/ci.yml` | lint, test, docs, build jobs |
| Adversarial job | `ci.yml` resilience job (stability-05) | 222/223 intermittent |
| Markers | `pyproject.toml`, `tests/adversarial/conftest.py` | `adversarial` marker |
| Coverage | pytest `--cov` in CI (if configured) | 77.65% measured |
| SOLID guards | `tests/test_solid_validation.py` | Line limits |
| Docs gate | `mkdocs build --strict` | Passing |

## Scope

- Encode merge thresholds: pytest 0 failures, ruff 0, mypy 0, format check, mkdocs strict, adversarial 100%.
- PR job boundaries: fast vs full vs scheduled soak.
- Deterministic wake test gate (after Phase 0 instrumentation).
- Coverage floor and optional ratchet.
- Clean-checkout packaging job.

## Non-goals

- Flaky test infinite reruns in CI.
- 100% coverage mandate.
- Nightly full adversarial on every PR (cost).

## Implementation slices

### Slice 6.1 -- PR fast gate (required)

Jobs on every PR:

```yaml
lint:
  - uv run ruff check src/ tests/
  - uv run ruff format --check src/ tests/
  - uv run mypy src/

test-fast:
  - uv run pytest tests/ -v --ignore=tests/adversarial/ -x

resilience:
  - uv run pytest tests/adversarial/ -v --tb=short

docs:
  - uv run mkdocs build --strict
```

### Slice 6.2 -- Merge gate (required on main / merge queue)

```yaml
test-full:
  - uv run pytest tests/ -v
  - coverage report --fail-under=77   # ratchet +0.5 after Phase 0 green
```

Exact thresholds:

| Check | Threshold |
|-------|-----------|
| Full pytest | 0 failures (baseline ≥1794 passed) |
| Adversarial | 223/223 pass |
| Ruff check | 0 errors |
| Ruff format | 0 files would reformat |
| Mypy `src/` | 0 errors |
| Coverage | ≥ **77.65%** initially; ratchet to **78%** after stabilization complete |
| MkDocs strict | pass |
| `uv build` | pass on clean checkout |

### Slice 6.3 -- Scheduled soak

Weekly cron (or nightly):

```bash
uv run pytest tests/adversarial/test_resource_exhaustion.py -v --count=50
uv run pytest tests/ -v --random-order
```

- Wake-source test 50x; fail if any leak delta > 0.
- Optional: 3x full suite for ordering sensitivity.

### Slice 6.4 -- Packaging job

```yaml
build-clean:
  - git archive HEAD | tar -x -C /tmp/hive-clean
  - cd /tmp/hive-clean && uv build
```

Excludes Conductor `.conductor/` artifact from failure signal.

### Slice 6.5 -- Branch protection documentation

1. Update `docs/contributing.md` merge requirements matching CI.
2. Link [framework-stabilization-index.md](framework-stabilization-index.md) exit criteria.

## Acceptance criteria

- [x] CI YAML merged with jobs above.
- [x] Simulated failure ( intentional ruff error ) blocks PR.
- [x] Coverage fail-under matches table.
- [x] Scheduled workflow runs on default branch.
- [x] Contributing docs list exact commands.

**Status:** VERIFIED (2026-07-25) — layered PR/merge gates in `.github/workflows/ci.yml`; weekly soak cron; coverage floor 77; clean-archive build job.

```bash
# Local mirror of merge gate
uv run pytest tests/adversarial/ -v --tb=short
uv run pytest tests/ -v
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run mkdocs build --strict
uv build
```

## Regression matrix (Hardening A--G)

CI must run:

- `tests/adversarial/test_shell_sandbox.py` (A)
- `tests/test_goal_lifecycle.py` (B)
- `tests/test_pursuit_transcript.py` (C)
- `tests/test_budget.py` (D)
- `tests/test_memory_unification.py` (E)
- `tests/adversarial/test_inter_agent_guardrails.py` (F)
- `tests/test_config.py` (G)

## Rollback / compatibility

- Coverage threshold lowering requires team approval only via PR comment.
- Soak job non-blocking initially optional `-- continue-on-error: false` after 2 green weeks.

## Dependencies

- **Phase 0** -- deterministic 223/223 adversarial.
- **Phases 1--5** -- final coverage after new tests; adjust fail-under once stable.

## Risks and YAGNI cuts

| Risk | Mitigation |
|------|------------|
| Flaky wake test blocks CI | Phase 0 must fix or quarantine with instrumentation proof |
| Coverage ratchet blocks WIP PRs | Ratchet only on main after stabilization exit |

**YAGNI:** Multi-OS matrix expansion; performance benchmarking job.

## Finding labels

| Finding | Label |
|---------|-------|
| 10 failing tests not in CI signal | **Verified defect** (gate gap) |
| 77.65% coverage unenforced | **Verified defect** |
| Wake intermittent | **Risk / hypothesis** until Phase 0 closes |
| Conductor uv build fail | **Risk / hypothesis** -- clean job isolates |
