---
description: Show tokens consumed since the start mark, without ending it (optional name)
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py:*)
---
!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py --span --name "$ARGUMENTS"`

Show the report above to the user as is, in at most two sentences of commentary.
