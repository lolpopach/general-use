---
description: Set up git worktrees for parallel Claude sessions
allowed-tools: Bash
---

Set up isolated worktrees so several Claude sessions can work at once without
fighting over one checkout.

For each task named in the arguments (default: 3 generically-named slots):

1. `git worktree add ../<repo>-<slug> -b claude/<slug>` off the current default
   branch.
2. Copy any untracked local config the tree needs to run (`.env`, local
   settings) — check `.gitignore` for what those are; do not copy secrets you
   were not told to.
3. Print a table: slug, path, branch, and the one-line task for that tree.

Then stop. Do not start work in the worktrees — I'll open a session in each.

Clean up finished ones with `git worktree remove <path>` and delete the branch.

Tasks: $ARGUMENTS
