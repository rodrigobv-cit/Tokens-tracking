---
description: Full report for a token window (skills in sequence, time, mode, tokens). Optional name.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py:*)
---
!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py --report --name "$ARGUMENTS"`

The report is printed above and saved as a .md file under ~/.claude/token-reports/.
Tell the user the saved path, the estimated total cost, and the two or three most notable findings (for example the top optimization suggestion, the biggest skill by context, idle time). Do not repeat the whole report.
