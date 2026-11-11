"""Rule-based token optimization suggestions for one measured window.

Each rule fires only when the window's own data shows the problem, and states
the evidence it saw. These are heuristics from a single window, not guarantees.
"""

ROUTINE_TOOLS = {"Read", "Grep", "Glob", "LS", "Bash", "WebFetch", "WebSearch", "NotebookRead"}
BIG_FAMILIES = ("claude-opus", "claude-fable", "claude-mythos")
PRIORITY = {"High": 0, "Medium": 1, "Low": 2}


def suggest(c, usd, dur, fmt, seq_text):
    """Return a list of (priority, title, evidence, action), most important first."""
    out = []

    def add(pri, title, evidence, action):
        out.append((pri, title, evidence, action))

    ci = c["cost_info"]
    parts = ci["parts"]
    total = parts["total"] if ci["priced"] else 0.0
    tot = c["tot"]

    # 1. Cache expired during pauses (5-minute TTL)
    if c["pauses"] and tot["c1h"] == 0 and c["pause_rewrites"]:
        longest = max(g for _, g, _ in c["pauses"])
        ev = (f"{len(c['pauses'])} pause(s) over 5 minutes (longest {dur(longest)}); after "
              f"{c['pause_rewrites']} of them most of the context was written to the cache again, "
              "and every write used the 5-minute TTL")
        if c["pause_rewrite_cost"]:
            ev += f" (about {usd(c['pause_rewrite_cost'])} in cache writes)"
        add("High", "Cache expired during pauses", ev + ".",
            "Keep gaps under 5 minutes, or use the 1-hour cache: it is reported to apply automatically on "
            "subscriptions, and with an API key you can set `ENABLE_PROMPT_CACHING_1H=1` or "
            "`CLAUDE_CODE_PROMPT_CACHE_TTL=1h` (verify both against your Claude Code version).")

    # 2. Model switches invalidate the cache
    if c["switch_rows"]:
        ev = (f"Model changed {len(c['switch_rows'])} time(s) ({seq_text(c['models'])}). Prompt caches are per "
              f"model, so the context was written again after each switch ({fmt(c['switch_write_tokens'])} tokens")
        ev += f", {usd(c['switch_write_cost'])}" if c["switch_write_cost"] else ""
        add("Medium", "Mid-task model switch", ev + ").",
            "Pick the model at the start of a task (`/model`), and switch at a natural break, ideally after "
            "`/clear` or `/compact`, when there is little context to re-write.")

    # 3. Haiku 5.5 over 100K prompt tokens
    if c["haiku_long"]:
        add("High", "Prompt over 100K tokens on Haiku 5.5",
            f"{c['haiku_long']} request(s) had prompts above 100K tokens and were billed at the higher "
            "Haiku 5.5 rate set (about 5x the input price).",
            "Keep the context under 100K tokens with `/compact` or `/clear`, or run that part on another model.")

    # 4. Compaction
    if c["compactions"]:
        o, a, b = c["compactions"][0]
        add("Medium", "Context was compacted or cleared",
            f"{len(c['compactions'])} sharp context drop(s), first at +{dur(o)} ({fmt(a)} to {fmt(b)} tokens). "
            "Compaction summarizes the whole context in an extra request and the next turns write a fresh cache.",
            "Compact yourself at a natural breakpoint with focused instructions (`/compact <what to keep>`), "
            "use `/clear` between unrelated tasks, or lower `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` to compact earlier.")

    # 5. Large context re-read every turn
    if c["peak"] >= 100000 or (total and parts["cache_read"] / total > 0.5):
        ev = f"Context peaked at {fmt(c['peak'])} tokens; the whole context is re-read on every turn"
        if total:
            ev += f" (cache reads were {100 * parts['cache_read'] / total:.0f}% of the estimated cost)"
        add("Medium", "Large context carried through the window", ev + ".",
            "Use `/clear` between tasks, send broad searches to a subagent (Explore) so their output does not "
            "stay in your context, trim big CLAUDE.md or memory files and unused MCP servers, and read large "
            "files with offset/limit.")

    # 6. Skills that add a lot of context, or reload
    for name, p in sorted(c["per_skill"].items(), key=lambda kv: -kv[1]["added"]):
        if p["added"] >= 5000:
            add("Medium", f"Skill `{name}` is heavy",
                f"It added about {fmt(p['added'])} tokens of context, which stay in the session and are re-read "
                "every turn afterwards.",
                "Invoke it only when needed, keep SKILL.md short and move reference detail into files read on demand.")
            break
    for name, p in c["per_skill"].items():
        if p["steps"] > 1:
            add("Low", f"Skill `{name}` loaded in {p['steps']} separate steps",
                f"It was used {p['calls']} time(s) across {p['steps']} steps, with other skills in between.",
                "Group the work that needs it so it loads once, and check it is not being re-read unnecessarily.")
            break

    # 7. Output-heavy cost
    if total and parts["output"] / total > 0.4:
        ev = f"Output tokens were {100 * parts['output'] / total:.0f}% of the estimated cost"
        if c["ratio"]:
            ev += f" (output costs {c['ratio']:.0f}x the input price on {c['last_key']})"
        if c["efforts"] and any(v in ("xhigh", "max") for _, v in c["efforts"]):
            ev += f"; effort was {seq_text(c['efforts'])}"
        add("Medium", "Output dominates the cost", ev + ".",
            "Lower effort for routine edits (`/effort low` or `medium`, or `CLAUDE_CODE_EFFORT_LEVEL`) and ask "
            "for concise answers; reserve high effort for hard reasoning.")

    # 8. Expensive model on routine tool work
    if c["top_key"] and c["top_key"].startswith(BIG_FAMILIES) and c["routine_share"] >= 0.7 and c["whatif_sonnet"]:
        top_cost = ci["by_model"][c["top_key"]]["cost"]
        if top_cost > c["whatif_sonnet_part"]:
            add("Medium", "Large model used for routine tool work",
                f"{100 * c['routine_share']:.0f}% of tool calls were read/search/shell, and {c['top_key']} made up "
                f"{usd(top_cost)} of the cost. The same tokens priced at Sonnet 5.5 would be about "
                f"{usd(c['whatif_sonnet_part'])} (rough: ignores tokenizer and capability differences).",
                "Use a smaller model for exploration and routine edits (`/model`), or run exploration in a "
                "subagent with a cheaper model, and keep the larger model for planning and hard problems.")

    # 9. Big tool outputs
    if c["jumps"]:
        top = c["jumps"][:3]
        add("Medium", "Large tool outputs entered the context",
            "Biggest jumps: " + ", ".join(f"{t} +{fmt(d)} tokens at +{dur(o)}" for d, t, o in top) + ".",
            "Read with offset/limit, grep before reading whole files, cap shell output (`| head`, `--stat`), "
            "and delegate wide searches to a subagent.")

    out.sort(key=lambda x: PRIORITY[x[0]])
    return out[:6]
