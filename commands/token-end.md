---
description: Mark the END of a token measurement and show tokens consumed (optional name)
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py:*)
---
!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py --mark end --name "$ARGUMENTS"`

Show the report above to the user as is, in at most two sentences of commentary.
