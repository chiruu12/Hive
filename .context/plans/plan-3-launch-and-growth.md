# Plan 3: Launch & Growth — Ship It, Get Stars

## Why This Third

Plan 1 made Hive solid. Plan 2 made it remarkable. Now package it for maximum
impact. A great framework nobody knows about gets zero stars. This plan turns
Hive into a project that looks professional, demos well, and spreads organically.

## Expected Outcome

After this plan, Hive has CI/CD, a docs site, contributor guidelines, a polished
web dashboard, a demo GIF, and launch posts ready for HN/Reddit/Twitter. First
release is on PyPI. Target: 50-100 stars in the first week, 200-300 within a month.

---

## Tasks (in execution order)

### 3.1 OSS Scaffolding — The Table Stakes
**Priority:** Critical | **Est:** 2-3 hours

No serious project ships without these. Missing any of them signals "hobby project."

- **CONTRIBUTING.md**: How to add tools, create profiles, write scenarios, run tests
- **CHANGELOG.md**: Version history from 0.1.0 to current
- **CODE_OF_CONDUCT.md**: Standard Contributor Covenant
- **.github/workflows/ci.yml**: Run tests + lint + mypy on every PR
- **.github/workflows/release.yml**: Build wheel + publish to PyPI on tag
- **.github/ISSUE_TEMPLATE/**: Bug report and feature request templates
- **.github/PULL_REQUEST_TEMPLATE.md**: PR checklist

**Files:** All new files in root and .github/

**Verify:** Push a PR → CI runs → tests pass → merge → release workflow triggers on tag

---

### 3.2 Documentation Site
**Priority:** High | **Est:** 3-4 hours

README is good but not enough. A docs site converts browsers into users.

- Use MkDocs + Material theme (standard for Python projects)
- Pages:
  - **Getting Started**: install, init, first run, watch agents
  - **Core Concepts**: daemon loop, existence loop, suffering, profiles
  - **CLI Reference**: every command with examples
  - **Python API**: `from hive import Hive` usage
  - **Writing Plugins**: toolkit contract, examples, hot-loading
  - **Tool Synthesis**: how agents create tools, safety guardrails
  - **Scenarios**: detective demo, benchmarks, custom scenarios
  - **Architecture**: module map, data flow, design decisions
  - **Model Support**: which models work, how to add providers
- Deploy to GitHub Pages via CI

**Files:** `mkdocs.yml` (new), `docs/` (new directory with .md files)

**Verify:** `mkdocs serve` → browse locally → all pages render, code examples highlighted

---

### 3.3 Web Dashboard — Beyond the Terminal
**Priority:** High | **Est:** 4-6 hours

The terminal TUI limits the audience. A web dashboard makes Hive accessible to
non-terminal users and produces better screenshots for social media.

- Lightweight: single HTML file served by a built-in HTTP server
- `hive dashboard` starts a local web server (port 8420)
- Real-time updates via SSE (Server-Sent Events) — no WebSocket complexity
- Panels:
  - Agent cards: name, role, model, status, current goal, suffering bar
  - Activity feed: real-time event stream with timestamps
  - Goal timeline: visual timeline of goals (generated → completed/abandoned)
  - Suffering graph: line chart per agent over time
  - Cost tracker: tokens used, USD spent, per-model breakdown
- Dark theme, responsive, no external dependencies (inline CSS/JS)
- Screenshot-friendly layout (designed for Twitter cards)

**Files:** `src/hive/dashboard/` (new: server.py, static/index.html), `src/hive/cli/main.py` (add dashboard command)

**Verify:** `hive start` in one terminal → `hive dashboard` → browser shows live agent activity

---

### 3.4 Demo Recording & GIF
**Priority:** High | **Est:** 2-3 hours

A 15-second GIF in the README is worth 1000 words. This is the single highest-ROI
item for GitHub stars.

- Record a terminal session showing:
  1. `hive init` (instant)
  2. `hive start -p coder,reviewer` (agents spawn)
  3. Agents generating goals, using tools, delegating
  4. Suffering escalating on one agent
  5. `hive status` showing the result
- Use `vhs` (Charm's terminal recorder) or `asciinema` for reproducible recordings
- Convert to GIF (<5MB) and embed in README
- Also record the detective demo as a separate GIF
- Record the web dashboard for a bonus GIF

**Files:** `demo/` (new: recording scripts, output GIFs), `README.md` (embed GIFs)

**Verify:** GIFs play smoothly in GitHub README, tell a clear story in <15 seconds

---

### 3.5 Leaderboard & Competition Mode
**Priority:** Medium | **Est:** 2-3 hours

Gamification drives engagement. People want to see their agents compete.

- `hive compete <scenario> --agents coder,researcher,tester --cycles 50`
- Agents compete on: goals completed, suffering endured, money earned, reputation gained
- Leaderboard table at the end with rankings
- Save competition results to `.hive/competitions/`
- `hive leaderboard` shows historical competition results
- Bonus: "agent of the week" — highest-performing agent across all runs

**Files:** `src/hive/competition/` (new: runner.py, leaderboard.py), `src/hive/cli/main.py` (add compete + leaderboard commands)

**Verify:** `hive compete survival --agents coder,researcher --cycles 20` → runs → shows leaderboard

---

### 3.6 Profile Sharing — Community Profiles
**Priority:** Medium | **Est:** 2 hours

Lower the barrier to interesting agent setups. Let people share profiles.

- `hive profile import <url-or-path>` — download a YAML profile
- `hive profile list` — show installed profiles (built-in + custom)
- `hive profile export <name>` — copy profile to clipboard or file
- Community profiles directory in repo: `profiles/community/`
- README section: "Share your profiles" with contribution guidelines

**Files:** `src/hive/cli/main.py` (add profile subcommands), `profiles/community/` (new)

**Verify:** Export a custom profile → import it on another machine → agent spawns with correct behavior

---

### 3.7 PyPI Publishing & First Release
**Priority:** Critical | **Est:** 1-2 hours

Ship v0.2.0 (or v0.3.0 post-Plan-2) to PyPI.

- Verify `pyproject.toml` metadata (description, classifiers, URLs, author)
- Test install from wheel in clean venv: `pip install dist/hive_agent-*.whl`
- Verify all CLI commands work post-install
- Publish to PyPI: `uv publish` or `twine upload dist/*`
- Create GitHub Release with changelog and download links
- Tag the release: `git tag v0.3.0 && git push --tags`

**Verify:** `pip install hive-agent` from PyPI → `hive init && hive start` works

---

### 3.8 Launch Posts
**Priority:** Critical | **Est:** 2-3 hours

The launch is a one-shot event. Maximize it.

**Hacker News (Show HN):**
- Title: "Show HN: Hive – An ant farm for AI agents (autonomous, suffering-driven, multi-model)"
- Body: 3-4 paragraphs — what it is, what makes it different (suffering system, tool synthesis, economy), quick start, link
- Time: Tuesday/Wednesday 10am ET (peak HN traffic)
- Include the detective demo as the hook

**Reddit (r/MachineLearning, r/LocalLLaMA, r/artificial):**
- Use /write-reddit-post skill for subreddit-appropriate tone
- r/LocalLLaMA angle: "runs with Ollama/LM Studio, no API key needed"
- r/MachineLearning angle: "model comparison through agent behavior"
- Include the benchmark results

**Twitter/X:**
- Thread format: hook → demo GIF → suffering system explanation → detective demo → link
- Tag relevant accounts (AI researchers, framework authors)

**LinkedIn:**
- Use /write-linkedin-post skill
- Professional angle: "What happens when you give AI agents jobs, money, and suffering?"

**Files:** `launch/` (new: hn-post.md, reddit-posts.md, twitter-thread.md, linkedin-post.md)

**Verify:** All posts written, links correct, GIFs embedded, timing planned

---

## Completion Criteria

- [ ] CI/CD runs on every PR, releases auto-publish to PyPI
- [ ] Docs site live on GitHub Pages
- [ ] Web dashboard shows real-time agent activity in browser
- [ ] Demo GIF embedded in README
- [ ] Competition mode works with leaderboard
- [ ] Profile import/export functional
- [ ] v0.3.0 published on PyPI
- [ ] Launch posts drafted for HN, Reddit, Twitter, LinkedIn

---

## Star Projection

| Source | Est. Stars | Notes |
|--------|-----------|-------|
| Hacker News front page | 80-150 | "Show HN" with good demo GIF |
| Reddit (3 subreddits) | 30-50 | r/LocalLLaMA most likely to convert |
| Twitter/X thread | 20-40 | If demo GIF goes viral |
| Organic discovery | 20-30 | PyPI, GitHub Explore, word of mouth |
| **Total (month 1)** | **150-270** | Conservative estimate |

The detective demo + suffering system + tool synthesis are the three hooks.
Lead with whichever gets the strongest reaction in the first 24 hours.
