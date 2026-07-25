# Phase A -- Shell containment

**Status:** Implemented (2026-07-23); follow-up hardening (2026-07-23)

## Goal

Close **critical shell jail bypasses** in restricted mode so file-reading commands cannot reach host paths via shell expansion or flag-value indirection, with adversarial tests that fail CI on regression.

## Follow-up hardening (2026-07-23)

Adversarial recheck found residual CRITICAL gaps after initial Phase A:

| ID | Finding | Fix |
|----|---------|-----|
| SEC-SHELL-03 | **Quoted paths** -- `cmd.split()` leaves quotes on tokens; jail treats `"/etc/passwd"` as a weird relative path inside workspace while the shell strips quotes and reads the host | Tokenize with `shlex.split(posix=True)` before path validation; reject invalid quoting |
| SEC-SHELL-04 | **Attached short-flag paths** -- `-o/tmp/out`, `-f/etc/hosts` skipped because the whole token is not a known flag | `_match_flag_with_value()` splits attached forms for path-taking flags |
| SEC-SHELL-05 | **`jq -L` library path** -- `-L` was in skip list; outside modules loadable | Treat `-L` / `--library-path` as path-value flags (including `-L/path`) |

Adversarial coverage: `TestQuotedPathBypass`, `TestAttachedFlagPathBypass` in `tests/adversarial/test_shell_sandbox.py`.

Second adversarial recheck (2026-07-23) found residual CRITICAL gaps in `sort`:

| ID | Finding | Fix |
|----|---------|-----|
| SEC-SHELL-06 | **`sort --files0-from`** -- list file is jailed but NUL-separated paths inside it are not; workspace list containing `/etc/passwd\0` reads host file | Reject `--files0-from` entirely in restricted mode |
| SEC-SHELL-07 | **`sort --compress-program`** -- flag was in skip list; workspace script executes arbitrarily (RCE) | Reject `--compress-program` entirely in restricted mode |

`-T` / `--temporary-directory` remain skipped (not jailed): sort may write temp files outside workspace (data-leak tradeoff); rejecting would break sort on non-writable workspaces.

Adversarial coverage: `TestSortDangerousFlags` in `tests/adversarial/test_shell_sandbox.py`.

## Why (problems addressed -- bullet list with severity)

- **CRITICAL:** `$HOME` / `~` expansion -- jail validates literal tokens (`~/.ssh/...`) but `asyncio.create_subprocess_shell` expands tildes at execution time (`src/hive/tools/shell/toolkit.py` `_check_paths_in_command` vs `shell_exec`).
- **CRITICAL:** Flag-value paths -- `sort -o /etc/passwd`, `grep -f /etc/passwd` skip path validation because value tokens are excluded from `_extract_path_args` (`_SORT_VALUE_FLAGS`, `_grep_path_args` without `-f` handling).
- **HIGH (adjacent):** `grep --file`, `sort --files0-from`, `cut -f` field specs vs paths -- similar parser gaps.
- **MED:** Residual dev-command RCE when `tools.shell_allow_dev_commands: true` -- documented, not removed (opt-in tier).

## Related issues bundled

| ID | Finding |
|----|---------|
| SEC-SHELL-01 | `$HOME` / `~` / `$VAR` path expansion bypass |
| SEC-SHELL-02 | `sort -o`, `grep -f`, `--output`, `--files0-from` |
| SEC-SHELL-03 | Adversarial coverage gaps in `tests/adversarial/test_shell_sandbox.py` |

## Current state (files)

| Area | Location | Behavior today |
|------|----------|----------------|
| Path jail | `src/hive/tools/shell/toolkit.py` | Resolves `(workspace / arg).resolve()` on raw tokens; no `expanduser` / env expansion |
| Subprocess | same file `shell_exec()` | `create_subprocess_shell(command, cwd=workspace, env HOME=workspace)` |
| Flag parsing | `_grep_path_args`, `_flagged_path_args`, `_SORT_VALUE_FLAGS` | Output/pattern file flags excluded from validation |
| Tests | `tests/adversarial/test_shell_sandbox.py` | Covers absolute paths, `../`, many read commands; **no** tilde/env/`-o`/`-f` cases |
| Docs | `docs/hardening-guide.md` Change 3 | Claims path jail on SAFE_COMMANDS |

## Proposed changes (numbered)

1. **Reject expansion-prone tokens before execution** in `_check_command()` or `_check_paths_in_command()`:
   - Reject args containing `~`, `$`, `` ` ``, or `%` (Windows-style) in path positions.
   - Reject bare `$HOME`, `${HOME}`, etc. even when jail would treat them as relative paths.

2. **Validate flag-value paths**, not only positional args:
   - Extend `_grep_path_args` to treat `-f`, `--file`, `--exclude-from` values as paths requiring workspace containment.
   - Extend `_flagged_path_args` for `sort` to validate `-o` / `--output` / `--files0-from` targets (still skip `-T` temp dir if it must stay internal -- document policy).
   - Audit `cut`, `diff`, `jq` for similar flags.

3. **Optional hardening (choose one, document tradeoff):**
   - **A (preferred for restricted mode):** Replace `create_subprocess_shell` with `create_subprocess_exec` + argv parsing for allowlisted commands (no shell expansion).
   - **B (minimal):** Keep shell but add pre-pass that expands/rejects using `os.path.expanduser` + explicit env map (only `HOME=workspace` allowed).

4. **Adversarial tests** in `tests/adversarial/test_shell_sandbox.py`:
   - `cat ~/.ssh/id_rsa`, `cat $HOME/.hive/hive.db`, `grep -f /etc/passwd x`, `sort -o /tmp/out lines.txt`.
   - Regression: workspace-relative reads still pass (`cat test.txt`, `sort -o out.txt lines.txt`).

5. **Docs:** Update `docs/hardening-guide.md` shell section + `docs/guide/toolkits.md` shell table with explicit "no tilde/env paths in restricted mode".

## Non-goals

- Disabling `allow_dev_commands` tier (already default `False` in `src/hive/config.py`).
- Container / Landlock / seccomp sandbox (deployment concern).
- Rewriting allowlist to remove `sort`, `grep`, etc.

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| Legitimate agent uses `~/workspace/foo` in scripts | Document workspace-relative paths only; error message suggests `foo` or `./foo` |
| `sort -o out` in workspace breaks if over-validated | Tests for allowed `-o` inside workspace |
| argv parsing drift vs shell | Restrict to SAFE_COMMANDS set; dev tier keeps shell |

Rollback: revert validation-only changes; keep new tests skipped with `@pytest.mark.xfail` only as temporary measure (prefer fix forward).

## Acceptance criteria (testable)

```bash
uv run pytest tests/adversarial/test_shell_sandbox.py -v --tb=short
uv run pytest tests/runtime/test_web_tools.py -q  # no shell regressions
```

- [x] `ShellToolkit(restrict=True, allow_dev_commands=False).shell_exec("cat ~/.ssh/id_rsa")` returns error before subprocess (or empty safe output), never host file contents.
- [x] `sort -o /etc/passwd ws.txt` and `grep -f /etc/passwd ws.txt` blocked with workspace escape message.
- [x] Existing `TestWorkspaceJail` tests remain green.
- [x] `docs/hardening-guide.md` documents tilde/env and flag-value policy.

## Suggested implementation order

1. Add failing adversarial tests (tilde, `$HOME`, `-o`, `-f`).
2. Token rejection for expansion metacharacters.
3. Flag-value path validation helpers (shared with `_flagged_path_args`).
4. Optional: subprocess_exec path for SAFE_COMMANDS.
5. Docs pass.

## Estimate

**M** (2--3 days): parser edge cases + tests + doc update.

## Dependencies (prior phases)

None. Should land **before** broader agent-loop phases so CI stays trustworthy.
