---
description: Prove the current change actually works, adversarially
allowed-tools: Bash, Read, Grep, Glob, Edit
---

Prove that the change currently in the working tree works. Not "looks right" —
works.

1. `git diff` (and `git status` for new files) to see exactly what changed.
2. State, in one line, what observable behavior should differ now.
3. Run something that would **fail if the change were wrong**: the test suite,
   a targeted test, or a script you write for this. Reproduce the old failure
   first when fixing a bug, then show it passing.
4. Re-read the diff hunting for what would break it: unhandled inputs, wrong
   branch taken, a caller you didn't update. Grep for other call sites.
5. Report the exact commands you ran and their real output.

If the change cannot be executed here, say so plainly and say what you checked
instead. Never substitute reasoning for a run and call it verified.

$ARGUMENTS
