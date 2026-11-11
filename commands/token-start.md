---
description: Mark the START of a token measurement (optional name)
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py:*)
---
!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py --mark start --name "$ARGUMENTS"`

Confirm in one line that the start mark was set. Do nothing else.
