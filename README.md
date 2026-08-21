# general-use

A personal utility repo, set up for working with Claude Code.

The interesting part is `.claude/` — a shared, version-controlled configuration
rather than per-machine settings:

```
CLAUDE.md                    working agreements + a running lessons log
.claude/settings.json        permission allowlist, formatting hook
.claude/hooks/format.sh      auto-formats every file Claude edits
.claude/commands/            /verify, /lesson, /parallel
.claude/agents/              verifier, simplifier
docs/claude-code-tips.md     where these conventions came from
```

Everything here is checked in on purpose: a setup that lives on one laptop
helps one person.
