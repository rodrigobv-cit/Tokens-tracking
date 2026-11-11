---
name: token-log
description: Report the last tool called in this session and its token usage, plus session totals, by reading the hook-written token log. Use when the user asks about last call tokens, context size, token usage per tool, or "how many tokens did that cost".
---

# token-log

A hook (`log_tokens.py`) appends one JSON line per tool call and per turn end to
`~/.claude/token-log.jsonl` (override with `CLAUDE_TOKEN_LOG`). Each line has the
real `usage` numbers from the transcript. This skill only reads that log.

## How to answer

1. Run the reader from this skill's folder:
   - Last call: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py`
   - Last N calls: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py --last 10`
   - Session totals and per-tool breakdown: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/token-log/scripts/read_log.py --summary`
   - Raw JSON: add `--json`
2. Report in one or two sentences: the last tool called, its context size and
   output tokens. For summaries, name the heaviest tool and the current context size.

## Start/end measurement

The user can bracket any stretch of work:
- `/token-start [name]` sets the start mark, `/token-end [name]` sets the end mark
  and prints the report, `/token-span [name]` previews it while still open.
- Equivalent script calls: `--mark start`, `--mark end`, `--span` (all take `--name`).
- "Consumed" = output + input + cache write tokens of assistant messages first
  seen after the start mark. Cache reads are reported separately because they
  are re-sent context, not new work.
- If asked in plain language ("start counting", "stop counting"), run the
  matching `--mark` command yourself. Marks only see turns already logged, so
  the report excludes the turn that issues the command.

## Full report

`/token-report [name]` (script: `--report --name x`) prints and saves a markdown
report for the window: status, session, directory, start/end, total window time
(active vs idle), Claude Code permission mode, model and effort level (each with
changes), token totals, a Configuration and caching section (cache on/off, TTL
split, hit rate, effective vs uncached input tokens, thinking, Claude Code version,
branch, service tier, token-related env vars), Other factors (subagent calls,
web requests, possible compaction), skills in sequence with context added and
time, main skills, tool flow and tool counts.

The **Skills flow** section is a Mermaid left-to-right diagram (Start, each skill
with offset, time and approximate context, End; the arrows list the tool work done
in between) followed by a table. The **Tool flow** section is a Mermaid top-down
diagram of consecutive tool steps (skills highlighted) plus a "In words" line and a
timeline table with offset, calls, duration, context change and output tokens per
step, then tool counts. Diagrams are capped (12 skills, 25 tool steps, 30 table
rows). Where Mermaid is not rendered, the fenced block is still readable text and
the tables carry the same facts.

It also has **Estimated cost** (API list-price equivalent: total with output, input,
cache write and cache read, by model, caching savings) and **Optimization
suggestions** (rule-based, each with the evidence it measured and what to do:
cache expiry during pauses, mid-task model switch, Haiku 5.5 over 100K, compaction,
large context, heavy skills, output-heavy cost, large model on routine work, large
tool outputs). Prices come from `pricing.json` next to this file (retrieved
2026-10-31 from the official pricing page); edit it or set `CLAUDE_TOKEN_PRICING`
when prices change or a model is missing. Models not in the table are listed as
"Not priced", never guessed. On a subscription the cost is a what-it-would-cost
figure, not a bill. Reports are saved to `~/.claude/token-reports/` (`CLAUDE_TOKEN_REPORTS`
overrides). Summarize the key findings and give the saved path; do not paste the
whole report back. Use `--no-save` to skip writing the file.

"Mode" is the permission mode the hook receives (default, acceptEdits, plan,
bypassPermissions). Entries logged before the hook was upgraded have no mode.

## Skills used in a window

The hook records `skill` on any call to the Skill tool, and on a Read of a
`.../<name>/SKILL.md` file. The span report ends with a "Skills used" list: name,
number of calls and approximate tokens of context each one added. Report that list
when the user asks which skills ran. Slash commands (`/token-start` etc.) are not
Skill tool calls, so they do not appear there.

## Field meanings

- `context_tokens` = input + cache read + cache creation: what the model saw on that turn.
- `output_tokens` = tokens generated in the assistant message that issued the tool call.
- Several tool calls can share one assistant message, so they repeat the same usage.
  The reader dedupes by `message_id` for totals.
- `tool` is empty on `Stop` events (end of turn).

## If the log is missing or empty

The hook is not active or no tool has run since. Tell the user to check that the plugin is enabled (`/plugin`) and restart the session, then retry.
Never estimate numbers by hand; report only what the log says.
