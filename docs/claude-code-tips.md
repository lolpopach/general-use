# Source: Boris Cherny's Claude Code tips

Origin: [Threads post, 2026-01-31](https://www.threads.com/@boris_cherny/post/DUMZr4VElyb)
(mirrored on [X](https://x.com/bcherny/status/2017742741636321619)).

> I'm Boris and I created Claude Code. I wanted to quickly share a few tips for
> using Claude Code, sourced directly from the Claude Code team. The way the
> team uses Claude is different than how I use it. Remember: there is no one
> right way to use Claude Code -- everyones' setup is different. You should
> experiment to see what works for you!

The Threads page renders only the root post; the follow-up posts holding the
tips did not come through. The list below is condensed from a
[third-party recap](https://www.anup.io/35-claude-code-tips-from-the-guy-who-built-it/)
of the same thread, so treat the wording as paraphrase, not quotation. A larger
collection attributed to the same author lives at
[howborisusesclaudecode.com](https://howborisusesclaudecode.com/).

## What this repo does about each tip

| Tip                                            | Applied here as                                 |
| ---------------------------------------------- | ----------------------------------------------- |
| Run sessions in parallel via git worktrees     | `/parallel` command                             |
| Pick one model, re-prompt instead of switching | CLAUDE.md → Workflow                            |
| Plan mode for complex tasks                    | CLAUDE.md → Workflow                            |
| CLAUDE.md as a living document                 | `CLAUDE.md` + `## Lessons` section              |
| `@.claude` in code review                      | Not configured — needs a GitHub app on the repo |
| Slash commands for repeated work               | `.claude/commands/`                             |
| Subagents for common workflows                 | `.claude/agents/{verifier,simplifier}.md`       |
| Hooks for automation                           | `.claude/hooks/format.sh` via `PostToolUse`     |
| Manage permissions, don't skip them            | `permissions.allow` / `deny` in settings        |
| Integrate your tools over MCP                  | Not configured — depends on your accounts       |
| Verification for long-running tasks            | `verifier` agent                                |
| **Give Claude a way to verify**                | CLAUDE.md, stated first; `/verify`              |
| Level up prompting                             | `/verify`'s "prove it" framing                  |
| Terminal setup, statusline, dictation          | Machine-local, not repo config                  |
| Use Claude as a learning tool                  | Per-session output style, not repo config       |
| Customise everything and share it              | This whole directory, checked into git          |

The four gaps are deliberate: they depend on accounts, a machine, or a session
preference, and hard-coding them into a shared repo would be wrong.
