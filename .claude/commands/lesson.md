---
description: Record a correction into CLAUDE.md so it doesn't recur
allowed-tools: Read, Edit, Bash
---

I just corrected you, or you found a mistake worth remembering. Turn it into
durable repo knowledge.

1. Identify the *general* rule behind the specific correction — not "use tabs
   here" but the convention it implies.
2. Check `CLAUDE.md` first: if a related rule already exists, sharpen it in
   place rather than adding a near-duplicate line.
3. Otherwise append one line to the `## Lessons` section. One line, imperative,
   no preamble, no dates.
4. Show me the resulting diff of CLAUDE.md and nothing else.

Keep the file short enough that it stays read. If Lessons grows past ~15 lines,
promote the recurring ones into `## Conventions` and drop the specifics.

The correction: $ARGUMENTS
