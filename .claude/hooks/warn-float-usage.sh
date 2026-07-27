#!/bin/bash
# PostToolUse advisory: exit 0 always, stderr text is a non-blocking warning
# (https://code.claude.com/docs/en/hooks - PostToolUse non-blocking warnings).
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

if grep -qE 'float\(|FloatField' "$FILE_PATH"; then
  echo "WARNING: '$FILE_PATH' contains float( or FloatField - CLAUDE.md requires Decimal for money." >&2
fi

exit 0
