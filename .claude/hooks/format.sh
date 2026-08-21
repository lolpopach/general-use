#!/usr/bin/env bash
# PostToolUse hook: format the file Claude just edited, using whatever the
# project has available. Never fails the tool call -- formatting is a
# convenience, not a gate.
set -uo pipefail

input="$(cat)"
file="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"

[ -n "$file" ] || exit 0
[ -f "$file" ] || exit 0

case "$file" in
  *.py)
    command -v ruff >/dev/null 2>&1 && ruff format -q "$file" >/dev/null 2>&1
    ;;
  *.js|*.jsx|*.ts|*.tsx|*.json|*.css|*.html|*.yaml|*.yml|*.md)
    command -v prettier >/dev/null 2>&1 && prettier --write --log-level silent "$file" >/dev/null 2>&1
    ;;
  *.go)
    command -v gofmt >/dev/null 2>&1 && gofmt -w "$file" >/dev/null 2>&1
    ;;
  *.sh|*.bash)
    # No formatter; just make sure it stays executable.
    chmod +x "$file" 2>/dev/null
    ;;
esac

exit 0
