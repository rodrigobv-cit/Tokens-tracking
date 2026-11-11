# Tokens-tracking

`token-log` is a Claude Code plugin that logs the real token usage of every tool call and turn,
then reports tokens, estimated cost, skills flow, cache behaviour and optimization suggestions.

## Install

```
/plugin marketplace add rodrigobv-cit/Tokens-tracking
/plugin install token-log@tokens-tracking
```

Restart the session so the hook loads.

## Use

| Command | What it does |
| --- | --- |
| `/token-start [name]` | Mark the start of a measurement |
| `/token-span [name]` | Show tokens since the start mark, without ending it |
| `/token-end [name]` | Mark the end and show tokens consumed |
| `/token-report [name]` | Full report, saved to `~/.claude/token-reports/` |

The `token-log` skill also answers "how many tokens did that cost?" from the log.
Log: `~/.claude/token-log.jsonl` (`CLAUDE_TOKEN_LOG`). Prices: `skills/token-log/pricing.json`
(`CLAUDE_TOKEN_PRICING`). Costs are API list-price equivalents, not a bill. Needs Python 3.8+.
See `examples/sample-report.md`.

## Standalone installer

Without the plugin system, `python3 install_token_log.py` installs the same hook, skill and
commands into `~/.claude`. Don't use both at once: the hook would log every call twice.
