# CLAUDE.md

Working agreements for Claude Code in this repo. This is a **living document**:
when Claude gets something wrong, the fix goes here, not just into the reply.

## What this repo is

`general-use` — a personal utility repo. Small scripts, one-off tools, and the
shared Claude Code configuration in `.claude/`. There is no single build system;
each tool carries its own, or none at all.

## Non-negotiable: give Claude a way to verify

Before writing code, establish how the change will be _proven_. A test, a script
that exercises it, a command whose output is checked — something Claude can run
and read. Work with no verification loop is a draft, not a change.

- Never report "done" on code that was never executed. Say what was run.
- If a change genuinely can't be verified here, say so explicitly in the reply.

## Workflow

- **Plan first on anything non-trivial.** Plan mode (`shift+tab` twice), iterate
  on the plan, then implement. Small, obvious edits skip this.
- **One model per task.** Don't switch mid-task; re-prompt instead. If the same
  prompt needs three attempts, the prompt is the problem.
- **Parallelize with worktrees, not checkouts.** See `/parallel`.
- **Minimal diffs.** Fix what was asked. Don't widen scope on your own.

## Conventions

- Shell scripts: `bash`, `set -euo pipefail`, executable bit set.
- Python: formatted with `ruff format`, linted with `ruff check`.
- JS/TS/JSON/MD: formatted with `prettier`.
- Formatting is automatic — a `PostToolUse` hook runs the right formatter after
  every edit. Don't hand-format, and don't commit a manual reformat.
- Commits: imperative subject, why-not-what body when the why isn't obvious.

## Permissions

Read-only inspection commands are pre-allowed in `.claude/settings.json`.
Anything that writes outside the repo, installs, or touches the network still
prompts. `--dangerously-skip-permissions` is not used here — if a command is
prompting often and is safe, add it to the allowlist instead.

## Custom commands and agents

| Thing              | Use it for                                             |
| ------------------ | ------------------------------------------------------ |
| `/verify`          | Prove a change actually works, adversarially           |
| `/lesson`          | Record a correction into this file so it doesn't recur |
| `/parallel`        | Set up N git worktrees for parallel Claude sessions    |
| `simplifier` agent | Post-implementation cleanup pass, quality only         |
| `verifier` agent   | Independent check that a claim of "done" holds up      |

## Lessons

Corrections captured over time. Append with `/lesson`; keep each to one line.

- Formatting is hook-driven; a diff full of whitespace changes means the hook
  was bypassed.
