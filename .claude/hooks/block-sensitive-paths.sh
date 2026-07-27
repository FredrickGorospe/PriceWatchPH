#!/bin/bash
# PreToolUse guard: exit 2 is the documented way to hard-block a tool call
# (https://code.claude.com/docs/en/hooks - only exit code 2 blocks the action).
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

BASENAME=$(basename "$FILE_PATH")

if [ "$BASENAME" = ".env" ] || [[ "$BASENAME" == *.env ]] || \
   [[ "$FILE_PATH" == *pgdata* ]] || [[ "$FILE_PATH" == *postgres-data* ]] || \
   [[ "$FILE_PATH" == *postgresql/data* ]]; then
  echo "Blocked: edits to '$FILE_PATH' are forbidden (env file or Postgres data directory)." >&2
  exit 2
fi

exit 0
