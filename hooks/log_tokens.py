#!/usr/bin/env python3
"""Claude Code hook: append the real token usage of the latest assistant
message to a JSONL log, tagged with the tool that was just called.

Wired to PostToolUse and Stop by hooks/hooks.json.
Log location: $CLAUDE_TOKEN_LOG or ~/.claude/token-log.jsonl
Never blocks Claude: always exits 0.

Besides token counts, each record keeps the settings that shape token use:
model, effort level, permission mode, cache TTL split, thinking blocks,
Claude Code version, subagent identity and relevant environment variables.
"""
import json
import os
import sys
import time
from pathlib import Path

LOG = Path(os.environ.get("CLAUDE_TOKEN_LOG", Path.home() / ".claude" / "token-log.jsonl"))
TAIL_BYTES = 600_000  # enough to cover the latest assistant message

# Environment variables that change how many tokens a session uses or bills.
# Only the ones that are set get logged (settings.json "env" values reach hooks too).
TRACKED_ENV = [
    "DISABLE_PROMPT_CACHING", "DISABLE_PROMPT_CACHING_HAIKU", "DISABLE_PROMPT_CACHING_SONNET",
    "DISABLE_PROMPT_CACHING_OPUS", "DISABLE_PROMPT_CACHING_FABLE",
    "ENABLE_PROMPT_CACHING_1H", "FORCE_PROMPT_CACHING_5M",
    "CLAUDE_CODE_PROMPT_CACHE_TTL", "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL",
    "CLAUDE_CODE_EFFORT_LEVEL", "MAX_THINKING_TOKENS",
    "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING", "CLAUDE_CODE_DISABLE_THINKING",
    "CLAUDE_CODE_DISABLE_1M_CONTEXT", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_CODE_DISABLE_FAST_MODE", "ANTHROPIC_MODEL",
]


def latest_assistant(transcript_path):
    """Return (entry, message, usage) of the last assistant entry that carries usage."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            data = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return None, None, None
    for line in reversed(data.splitlines()):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message") or {}
        usage = msg.get("usage")
        if usage:
            return entry, msg, usage
    return None, None, None


def skill_name(payload):
    """Name of the skill this tool call used, if any.

    - Skill tool:  tool_input.skill
    - Read of .../skills/<name>/SKILL.md (skills loaded by reading the file)
    """
    tool = payload.get("tool_name")
    inp = payload.get("tool_input") or {}
    if tool == "Skill":
        return inp.get("skill") or inp.get("name")
    if tool == "Read":
        parts = Path(str(inp.get("file_path", ""))).parts
        if parts and parts[-1] == "SKILL.md" and len(parts) >= 2:
            return parts[-2]
    return None


def effort_level(payload):
    eff = payload.get("effort")
    if isinstance(eff, dict):
        return eff.get("level")
    return eff if isinstance(eff, str) else None


def thinking_blocks(msg):
    content = msg.get("content")
    if not isinstance(content, list):
        return 0
    return sum(1 for b in content if isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking"))


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    transcript = payload.get("transcript_path")
    if not transcript:
        return

    entry, msg, usage = latest_assistant(transcript)
    if not usage:
        return

    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    c_read = usage.get("cache_read_input_tokens", 0) or 0
    c_create = usage.get("cache_creation_input_tokens", 0) or 0
    cc = usage.get("cache_creation") or {}          # TTL split of the cache writes
    stu = usage.get("server_tool_use") or {}        # server-side web tools

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session_id": payload.get("session_id"),
        "event": payload.get("hook_event_name"),
        "tool": payload.get("tool_name"),  # None on Stop
        "tool_use_id": payload.get("tool_use_id"),
        "skill": skill_name(payload),  # None unless this call used a skill
        "message_id": msg.get("id"),
        "model": msg.get("model"),
        # Claude Code permission mode: default | acceptEdits | plan | bypassPermissions ...
        "permission_mode": payload.get("permission_mode"),
        "effort": effort_level(payload),  # low | medium | high | xhigh | max
        "agent_type": payload.get("agent_type"),  # set when the call came from a subagent
        "agent_id": payload.get("agent_id"),
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": c_read,
        "cache_creation_tokens": c_create,
        "cache_5m_tokens": cc.get("ephemeral_5m_input_tokens") or 0,
        "cache_1h_tokens": cc.get("ephemeral_1h_input_tokens") or 0,
        "context_tokens": inp + c_read + c_create,  # what the model saw this turn
        "thinking_blocks": thinking_blocks(msg),    # thinking tokens are inside output_tokens
        "service_tier": usage.get("service_tier"),
        "web_searches": stu.get("web_search_requests") or 0,
        "web_fetches": stu.get("web_fetch_requests") or 0,
        "cc_version": (entry or {}).get("version"),
        "git_branch": (entry or {}).get("gitBranch"),
        "sidechain": bool((entry or {}).get("isSidechain")),
        "cwd": payload.get("cwd"),
    }
    env = {k: os.environ[k] for k in TRACKED_ENV if os.environ.get(k)}
    if env:
        record["env"] = env

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a logging hook must never break the session
    sys.exit(0)
