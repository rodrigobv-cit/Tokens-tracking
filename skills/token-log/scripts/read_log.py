#!/usr/bin/env python3
"""Read the token log written by log_tokens.py.

Examples:
  read_log.py                      # last call in the most recent session
  read_log.py --last 10            # last 10 calls
  read_log.py --summary            # totals per tool + session totals
  read_log.py --session <id>       # pick a session (default: most recent)
  read_log.py --all-sessions       # don't filter by session
  read_log.py --json               # machine-readable output
  read_log.py --mark start [--name x]   # drop a start marker
  read_log.py --mark end   [--name x]   # drop an end marker and print the span
  read_log.py --span [--name x]         # tokens consumed since the start marker
  read_log.py --report [--name x]       # full markdown report, saved to ~/.claude/token-reports/
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advice  # noqa: E402
import costing  # noqa: E402

usd = costing.usd

LOG = Path(os.environ.get("CLAUDE_TOKEN_LOG", Path.home() / ".claude" / "token-log.jsonl"))
REPORT_DIR = Path(os.environ.get("CLAUDE_TOKEN_REPORTS", LOG.parent / "token-reports"))


def load():
    if not LOG.exists():
        sys.exit(f"No log found at {LOG}. Is the hook installed and has a tool run yet?")
    rows = []
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def fmt(n):
    return f"{n:,}"


def show_rows(rows):
    print(f"{'time':<20} {'event':<12} {'tool':<18} {'context':>10} {'out':>8} {'cache_rd':>10} {'cache_wr':>10}")
    for r in rows:
        print(
            f"{r['ts'][:19].replace('T', ' '):<20} {str(r.get('event')):<12} "
            f"{str(r.get('tool') or '-'):<18} {fmt(r['context_tokens']):>10} "
            f"{fmt(r['output_tokens']):>8} {fmt(r['cache_read_tokens']):>10} "
            f"{fmt(r['cache_creation_tokens']):>10}"
        )


def summary(rows):
    # Several tool calls can share one assistant message; count each message once.
    seen, tot = set(), defaultdict(int)
    per_tool = defaultdict(lambda: {"calls": 0, "out": 0, "ctx_max": 0})
    for r in rows:
        t = r.get("tool") or "(stop)"
        pt = per_tool[t]
        pt["calls"] += 1
        pt["out"] += r["output_tokens"]
        pt["ctx_max"] = max(pt["ctx_max"], r["context_tokens"])
        mid = r.get("message_id") or id(r)
        if mid in seen:
            continue
        seen.add(mid)
        tot["input"] += r["input_tokens"]
        tot["output"] += r["output_tokens"]
        tot["cache_read"] += r["cache_read_tokens"]
        tot["cache_creation"] += r["cache_creation_tokens"]
    last = rows[-1]
    print(f"Session: {last.get('session_id')}")
    print(f"Assistant messages: {len(seen)}   logged calls: {len(rows)}")
    print(f"Current context size (last call): {fmt(last['context_tokens'])}")
    print(
        f"Totals (deduped by message): input {fmt(tot['input'])} | output {fmt(tot['output'])} | "
        f"cache read {fmt(tot['cache_read'])} | cache write {fmt(tot['cache_creation'])}"
    )
    print()
    print(f"{'tool':<20} {'calls':>6} {'out tokens':>12} {'peak context':>14}")
    for t, v in sorted(per_tool.items(), key=lambda kv: -kv[1]["out"]):
        print(f"{t:<20} {v['calls']:>6} {fmt(v['out']):>12} {fmt(v['ctx_max']):>14}")


def context_pct(session_id):
    """Context window % for a session, as written by the status line script; None if unknown.

    The percentage can only come from Claude Code itself (the window size depends on the
    model and plan), so it is read from ~/.claude/context-pct/<session_id> (override the
    folder with CLAUDE_CONTEXT_PCT_DIR) and ignored when older than 10 minutes.
    """
    sid = str(session_id or "")
    if not sid or not all(c.isalnum() or c in "-_" for c in sid):
        return None
    d = Path(os.environ.get("CLAUDE_CONTEXT_PCT_DIR", Path.home() / ".claude" / "context-pct"))
    f = d / sid
    try:
        if time.time() - f.stat().st_mtime > 600:
            return None
        return int(f.read_text().strip())
    except (OSError, ValueError):
        return None


def pct_badge(pct):
    """Traffic-light marker: green below 25%, yellow up to 40%, red above."""
    return ("\U0001F7E2" if pct < 25 else "\U0001F7E1" if pct <= 40 else "\U0001F534") + f" {pct}%"


def is_mark(r):
    return r.get("type") == "mark"


def add_mark(rows, label, name):
    """Append a start/end marker to the log, tagged with the current session."""
    usage = [r for r in rows if not is_mark(r)]
    if not usage:
        sys.exit("Nothing logged yet, so there is no session to mark.")
    mark = {
        "type": "mark",
        "label": label,
        "name": name,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session_id": usage[-1].get("session_id"),
    }
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(mark, ensure_ascii=False) + "\n")
    pct = context_pct(mark["session_id"])
    pct_txt = f", {pct_badge(pct)} of the window" if pct is not None else ""
    print(f"Marked {label} '{name}' at {mark['ts'][:19].replace('T', ' ')} "
          f"(context so far: {fmt(usage[-1]['context_tokens'])} tokens{pct_txt})")


def locate(rows, name):
    """Find the latest start mark called `name` and the usage rows inside its window."""
    starts = [i for i, r in enumerate(rows) if is_mark(r) and r["label"] == "start" and r["name"] == name]
    if not starts:
        sys.exit(f"No start mark named '{name}'. Run: read_log.py --mark start --name {name}")
    sid = rows[starts[-1]].get("session_id")
    rows = [r for r in rows if r.get("session_id") == sid]
    s = next(i for i in range(len(rows) - 1, -1, -1)
             if is_mark(rows[i]) and rows[i]["label"] == "start" and rows[i]["name"] == name)
    e = next((i for i in range(s + 1, len(rows))
              if is_mark(rows[i]) and rows[i]["label"] == "end" and rows[i]["name"] == name), None)
    stop = e if e is not None else len(rows)
    return {
        "rows": rows, "s": s, "e": e, "stop": stop,
        "before": [r for r in rows[:s] if not is_mark(r)],
        "window": [r for r in rows[s + 1:stop] if not is_mark(r)],
    }


def span(rows, name):
    """Tokens consumed between the latest start mark and its end mark (or now)."""
    loc = locate(rows, name)
    rows, s, e, before, window = loc["rows"], loc["s"], loc["e"], loc["before"], loc["window"]
    already = {r.get("message_id") for r in before}  # messages that predate the span

    seen, tot = set(), defaultdict(int)
    tools = defaultdict(int)
    peak = 0
    for r in window:
        peak = max(peak, r["context_tokens"])
        if r.get("tool"):
            tools[r["tool"]] += 1
        mid = r.get("message_id")
        if mid in already or mid in seen:
            continue
        seen.add(mid)
        tot["input"] += r["input_tokens"]
        tot["output"] += r["output_tokens"]
        tot["cache_read"] += r["cache_read_tokens"]
        tot["cache_creation"] += r["cache_creation_tokens"]

    # Skills used in the window, with the approximate context they added:
    # context of the next assistant message minus context of the message that called the skill.
    skills = defaultdict(lambda: {"calls": 0, "added": 0})
    for i, r in enumerate(window):
        name_ = r.get("skill")
        if not name_:
            continue
        skills[name_]["calls"] += 1
        nxt = next((x for x in window[i + 1:] if x.get("message_id") != r.get("message_id")), None)
        if nxt:
            skills[name_]["added"] += max(0, nxt["context_tokens"] - r["context_tokens"])

    state = "closed" if e is not None else "open (no end mark yet, counting up to the last logged call)"
    t0 = rows[s]["ts"][:19].replace("T", " ")
    t1 = (rows[e]["ts"] if e is not None else (window[-1]["ts"] if window else rows[s]["ts"]))[:19].replace("T", " ")
    new_tokens = tot["input"] + tot["output"] + tot["cache_creation"]
    print(f"Span '{name}' [{state}]  {t0} -> {t1}")
    print(f"Assistant messages: {len(seen)}   tool calls: {sum(tools.values())}")
    print(f"Consumed: {fmt(new_tokens)} new tokens "
          f"(output {fmt(tot['output'])} + input {fmt(tot['input'])} + cache write {fmt(tot['cache_creation'])})")
    print(f"Cache reads (re-sent context, billed cheaper): {fmt(tot['cache_read'])}")
    ctx0 = before[-1]["context_tokens"] if before else 0
    ctx1 = window[-1]["context_tokens"] if window else ctx0
    print(f"Context size: {fmt(ctx0)} -> {fmt(ctx1)} (peak {fmt(peak)})")
    if tools:
        top = ", ".join(f"{t} x{n}" for t, n in sorted(tools.items(), key=lambda kv: -kv[1])[:6])
        print(f"Tools: {top}")
    if skills:
        print("Skills used (context added is approximate: it includes whatever else entered the context at that step):")
        for n, v in sorted(skills.items(), key=lambda kv: -kv[1]["added"]):
            print(f"  {n}: {v['calls']} call(s), ~{fmt(v['added'])} tokens of context")
    else:
        print("Skills used: none")


MODE_LABELS = {
    "default": "default (asks before edits and commands)",
    "acceptEdits": "accept edits (file edits auto-approved)",
    "plan": "plan mode (planning, no changes)",
    "bypassPermissions": "bypass permissions (nothing asks)",
}
IDLE_GAP = 300  # seconds; longer gaps between events count as idle time


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def dur(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def changes(window, key, off):
    """[(offset_seconds, value)] each time `key` takes a new value inside the window."""
    out = []
    for r in window:
        v = r.get(key)
        if v and (not out or out[-1][1] != v):
            out.append((off(r), v))
    return out


def seq_text(seq):
    if not seq:
        return "not recorded"
    return " → ".join(v + (f" (at +{dur(o)})" if i else "") for i, (o, v) in enumerate(seq))


def build_runs(window, off, total):
    """Consecutive calls of the same tool (or skill) as timed steps."""
    runs, counted = [], set()
    for r in window:
        if not r.get("tool"):
            continue
        label = f"Skill: {r['skill']}" if r.get("skill") else r["tool"]
        if runs and runs[-1]["label"] == label:
            runs[-1]["calls"] += 1
        else:
            runs.append({"label": label, "skill": r.get("skill"), "at": off(r), "calls": 1, "first": r, "out": 0})
        mid = r.get("message_id")
        if mid not in counted:  # a message that issued several tool calls counts once
            counted.add(mid)
            runs[-1]["out"] += r["output_tokens"]
    for i, run in enumerate(runs):
        nxt = runs[i + 1] if i + 1 < len(runs) else None
        run["dur"] = (nxt["at"] if nxt else total) - run["at"]
        end_ctx = nxt["first"]["context_tokens"] if nxt else window[-1]["context_tokens"]
        run["ctx_delta"] = end_ctx - run["first"]["context_tokens"]
    return runs


def mm(text):
    """Make text safe inside a quoted Mermaid label."""
    for a, b in (('"', "'"), ("[", "("), ("]", ")"), ("{", "("), ("}", ")"), ("<", "‹"), (">", "›"), ("|", "/"), ("#", "no.")):
        text = str(text).replace(a, b)
    return text


def mermaid_tool_flow(runs, cap=25):
    """Vertical flowchart of tool steps; skill steps are highlighted."""
    shown = runs[:cap]
    lines = ["```mermaid", "flowchart TD"]
    for i, r in enumerate(shown, 1):
        label = r["label"] + (f" ×{r['calls']}" if r["calls"] > 1 else "")
        lines.append(f'    T{i}["{mm(label)}<br/>+{dur(r["at"])} · {dur(r["dur"])}"]')
    n = len(shown)
    if len(runs) > cap:
        n += 1
        lines.append(f'    T{n}["… {len(runs) - cap} more step(s)"]')
    for i in range(1, n):
        lines.append(f"    T{i} --> T{i + 1}")
    skill_nodes = [f"T{i}" for i, r in enumerate(shown, 1) if r["skill"]]
    lines.append("    classDef skill fill:#fde68a,stroke:#b45309,color:#000")
    if skill_nodes:
        lines.append("    class " + ",".join(skill_nodes) + " skill")
    lines.append("```")
    return lines


def mermaid_skill_flow(steps, runs, total, cap=12):
    """Left-to-right flow Start -> skills -> End; edges list the tool work done in between."""
    shown = steps[:cap]
    bounds = [s["at"] for s in shown] + [float("inf")]

    def between(lo, hi):
        counts = defaultdict(int)
        for r in runs:
            if not r["skill"] and lo <= r["at"] < hi:
                counts[r["label"]] += r["calls"]
        return ", ".join(f"{t} ×{n}" if n > 1 else t for t, n in counts.items())

    lines = ["```mermaid", "flowchart LR", '    S0(["Start"])']
    for i, s in enumerate(shown, 1):
        lines.append(f'    S{i}["{mm(s["name"])}<br/>+{dur(s["at"])} · {dur(s["time"])}<br/>~{fmt(s["added"])} tokens"]')
    last = len(shown) + 1
    lines.append(f'    S{last}(["{"End" if len(steps) <= cap else f"… {len(steps) - cap} more"}"])')
    chain = [(0, -1.0)] + [(i, s["at"]) for i, s in enumerate(shown, 1)]
    for k, (idx, at) in enumerate(chain):
        nxt_at = bounds[k]
        label = between(at if idx else -1.0, nxt_at)
        arrow = f'-->|"{mm(label)}"|' if label else "-->"
        lines.append(f"    S{idx} {arrow} S{idx + 1}")
    lines.append("    classDef skill fill:#fde68a,stroke:#b45309,color:#000")
    lines.append("    class " + ",".join(f"S{i}" for i in range(1, len(shown) + 1)) + " skill")
    lines.append("```")
    return lines


def report(rows, name, save=True):
    """Markdown report for one start/end window: skills in order, time, mode, tokens."""
    loc = locate(rows, name)
    rows, s, e, before, window = loc["rows"], loc["s"], loc["e"], loc["before"], loc["window"]
    already = {r.get("message_id") for r in before}
    start = parse_ts(rows[s]["ts"])
    end_iso = rows[e]["ts"] if e is not None else (window[-1]["ts"] if window else rows[s]["ts"])
    end = parse_ts(end_iso)
    total = (end - start).total_seconds()
    off = lambda r: (parse_ts(r["ts"]) - start).total_seconds()  # noqa: E731

    # time: wall clock, plus active time (gaps up to IDLE_GAP) and the longest pause
    stamps = [start] + [parse_ts(r["ts"]) for r in window] + ([end] if e is not None else [])
    active = longest = 0
    for a, b in zip(stamps, stamps[1:]):
        g = (b - a).total_seconds()
        longest = max(longest, g)
        if g <= IDLE_GAP:
            active += g

    # tokens (each assistant message counted once, only if it started inside the window)
    seen, tot, msg_rows = set(), defaultdict(int), []
    for r in window:
        mid = r.get("message_id")
        if mid in already or mid in seen:
            continue
        seen.add(mid)
        msg_rows.append(r)
        tot["c5m"] += r.get("cache_5m_tokens") or 0
        tot["c1h"] += r.get("cache_1h_tokens") or 0
        tot["web"] += (r.get("web_searches") or 0) + (r.get("web_fetches") or 0)
        tot["think_msgs"] += 1 if r.get("thinking_blocks") else 0
        tot["input"] += r["input_tokens"]
        tot["output"] += r["output_tokens"]
        tot["cache_read"] += r["cache_read_tokens"]
        tot["cache_creation"] += r["cache_creation_tokens"]
    new_tokens = tot["input"] + tot["output"] + tot["cache_creation"]
    ctx0 = before[-1]["context_tokens"] if before else 0
    ctx1 = window[-1]["context_tokens"] if window else ctx0
    peak = max([r["context_tokens"] for r in window] + [ctx0])
    pricing = costing.load_pricing()
    cost_info = costing.summarize(pricing, msg_rows)

    # mode and model, in order of appearance
    modes = []
    for r in window:
        m = r.get("permission_mode")
        if m and (not modes or modes[-1][1] != m):
            modes.append((off(r), m))
    models = changes(window, "model", off)
    efforts = changes(window, "effort", off)
    versions = sorted({r["cc_version"] for r in window if r.get("cc_version")})
    branches = sorted({r["git_branch"] for r in window if r.get("git_branch")})
    tiers = sorted({r["service_tier"] for r in window if r.get("service_tier")})
    env = {}
    for r in window:
        env.update(r.get("env") or {})
    sub_calls = defaultdict(int)
    for r in window:
        if r.get("tool") and (r.get("agent_type") or r.get("agent_id")):
            sub_calls[r.get("agent_type") or "subagent"] += 1
    compactions = []
    prev = before[-1] if before else None
    for r in window:
        if prev and r.get("message_id") != prev.get("message_id"):
            drop = prev["context_tokens"] - r["context_tokens"]
            if drop > max(20000, 0.3 * prev["context_tokens"]):
                compactions.append((off(r), prev["context_tokens"], r["context_tokens"]))
        prev = r

    # skills in sequence; a skill call followed by a read of its SKILL.md is one step
    steps = []
    for i, r in enumerate(window):
        sk = r.get("skill")
        if not sk:
            continue
        nxt = next((x for x in window[i + 1:] if x.get("message_id") != r.get("message_id")), None)
        added = max(0, nxt["context_tokens"] - r["context_tokens"]) if nxt else 0
        if steps and steps[-1]["name"] == sk:
            steps[-1]["calls"] += 1
            steps[-1]["added"] += added
        else:
            steps.append({"name": sk, "at": off(r), "calls": 1, "added": added})
    for i, st in enumerate(steps):
        st["time"] = (steps[i + 1]["at"] if i + 1 < len(steps) else total) - st["at"]

    per_skill = {}
    for st in steps:
        p = per_skill.setdefault(st["name"], {"steps": 0, "calls": 0, "added": 0, "time": 0})
        p["steps"] += 1
        p["calls"] += st["calls"]
        p["added"] += st["added"]
        p["time"] += st["time"]

    # tool flow and counts
    flow, tools = [], defaultdict(int)
    for r in window:
        t = r.get("tool")
        if not t:
            continue
        tools[t] += 1
        label = f"{t}({r['skill']})" if r.get("skill") else t
        if flow and flow[-1][0] == label:
            flow[-1][1] += 1
        else:
            flow.append([label, 1])
    turns = sum(1 for r in window if r.get("event") == "Stop")
    ncalls = sum(tools.values())
    runs = build_runs(window, off, total) if ncalls else []

    # ---- inputs for the cost section and the suggestions
    pauses, prev_ts = [], start
    for r in window:
        t = parse_ts(r["ts"])
        if (t - prev_ts).total_seconds() > IDLE_GAP:
            pauses.append((off(r), (t - prev_ts).total_seconds(), r))
        prev_ts = t
    pause_rewrites, pause_rewrite_cost = 0, 0.0
    for _, _, r in pauses:
        if r["context_tokens"] and r["cache_creation_tokens"] > 0.3 * r["context_tokens"]:
            pause_rewrites += 1
            p = costing.price(pricing, r)
            if p:
                pause_rewrite_cost += p["cache_write"]
    switch_rows, prev_model = [], (before[-1].get("model") if before else None)
    for r in window:
        m = r.get("model")
        if m and prev_model and m != prev_model:
            switch_rows.append(r)
        if m:
            prev_model = m
    switch_write_tokens = sum(r["cache_creation_tokens"] for r in switch_rows)
    switch_write_cost = sum((costing.price(pricing, r) or {}).get("cache_write", 0) for r in switch_rows)
    tiered_long = 0
    for r in msg_rows:
        k = costing.find_model(pricing, r.get("model"))
        if k and pricing["models"][k].get("long") and r["context_tokens"] > pricing["models"][k].get("long_over", 100000):
            tiered_long += 1
    jumps, seen_j = [], set()
    for i, r in enumerate(window):
        mid = r.get("message_id")
        if not r.get("tool") or r.get("skill") or mid in seen_j:
            continue
        seen_j.add(mid)
        nxt = next((x for x in window[i + 1:] if x.get("message_id") != mid), None)
        if nxt and nxt["context_tokens"] - r["context_tokens"] > 8000:
            jumps.append((nxt["context_tokens"] - r["context_tokens"], r["tool"], off(r)))
    jumps.sort(reverse=True)
    top_key = max(cost_info["by_model"], key=lambda k: cost_info["by_model"][k]["cost"]) if cost_info["by_model"] else None
    routine_share = sum(n for t, n in tools.items() if t in advice.ROUTINE_TOOLS) / ncalls if ncalls else 0
    whatif_part = 0.0
    if top_key and "claude-sonnet-5-5" in pricing["models"]:
        whatif_part = costing.whatif(
            pricing, [r for r in msg_rows if costing.find_model(pricing, r.get("model")) == top_key],
            "claude-sonnet-5-5") or 0.0
    ratio = (pricing["models"][top_key]["out"] / pricing["models"][top_key]["in"]) if top_key else 0
    ctx = {
        "cost_info": cost_info, "tot": tot, "pauses": pauses, "pause_rewrites": pause_rewrites,
        "pause_rewrite_cost": pause_rewrite_cost, "switch_rows": switch_rows, "models": models,
        "switch_write_tokens": switch_write_tokens, "switch_write_cost": switch_write_cost,
        "haiku_long": tiered_long, "compactions": compactions, "peak": peak, "per_skill": per_skill,
        "ratio": ratio, "last_key": top_key, "efforts": efforts, "top_key": top_key,
        "routine_share": routine_share, "whatif_sonnet": bool(whatif_part),
        "whatif_sonnet_part": whatif_part, "jumps": jumps,
    }

    closed = e is not None
    L = []
    L.append(f"# Token window report: {name}")
    L.append("")
    L.append(f"- **Status:** {'closed' if closed else 'open (no end mark; counted up to the last logged call)'}")
    L.append(f"- **Session:** `{rows[s].get('session_id')}`" +
             (f"   **Directory:** `{window[0].get('cwd')}`" if window and window[0].get("cwd") else ""))
    L.append(f"- **Started:** {start:%Y-%m-%d %H:%M:%S}   **Ended:** {end:%Y-%m-%d %H:%M:%S}")
    L.append(f"- **Total window time:** {dur(total)} (active {dur(active)}, "
             f"idle {dur(total - active)}, longest pause {dur(longest)})")
    if modes:
        txt = " → ".join(f"{MODE_LABELS.get(m, m)}" + (f" (at +{dur(o)})" if i else "") for i, (o, m) in enumerate(modes))
        L.append(f"- **Claude Code mode:** {txt}")
    else:
        L.append("- **Claude Code mode:** not recorded (entries predate this field, or the hook is not active; check the plugin is enabled and restart the session)")
    L.append(f"- **Model:** {seq_text(models)}")
    L.append(f"- **Effort level:** {seq_text(efforts) if efforts else 'not recorded (older entries, or no effort field in the hook payload)'}")
    L.append("")
    L.append("## Tokens")
    L.append("")
    L.append(f"- **Consumed (new):** {fmt(new_tokens)} = output {fmt(tot['output'])} + input {fmt(tot['input'])} "
             f"+ cache write {fmt(tot['cache_creation'])}")
    L.append(f"- **Cache reads (re-sent context):** {fmt(tot['cache_read'])}")
    L.append(f"- **Context size:** {fmt(ctx0)} → {fmt(ctx1)} (peak {fmt(peak)})")
    L.append(f"- **Activity:** {len(seen)} assistant message(s), {ncalls} tool call(s), {turns} completed turn(s)")
    L.append("")
    # ---- estimated cost
    meta = pricing.get("meta", {})
    L.append("## Estimated cost (API list-price equivalent)")
    L.append("")
    if cost_info["priced"]:
        pt = cost_info["parts"]
        L.append(f"- **Total:** {usd(pt['total'])} = output {usd(pt['output'])} + input {usd(pt['input'])} "
                 f"+ cache write {usd(pt['cache_write'])} + cache read {usd(pt['cache_read'])}")
        L.append(f"- **Average per assistant message:** {usd(pt['total'] / cost_info['priced'])} "
                 f"over {cost_info['priced']} priced message(s)")
        L.append("- **By model:** " + ", ".join(
            f"{k} {usd(v['cost'])} ({v['messages']} msg)"
            for k, v in sorted(cost_info["by_model"].items(), key=lambda kv: -kv[1]["cost"])))
        if cost_info["input_side_uncached"]:
            a, b = cost_info["input_side"], cost_info["input_side_uncached"]
            L.append(f"- **Caching effect:** input side cost {usd(a)} instead of {usd(b)} without caching "
                     f"(saved {usd(b - a)}, {100 * (1 - a / b):.0f}%)")
    else:
        L.append("- No message could be priced (model not recorded, or not listed in pricing.json).")
    if cost_info["unpriced"]:
        L.append(f"- **Not priced:** {cost_info['unpriced']} message(s) on {', '.join(cost_info['unpriced_models'])}; "
                 "add them to pricing.json to include them.")
    L.append(f"- **Prices:** list prices from pricing.json (source: {meta.get('source', 'unknown')}, "
             f"retrieved {meta.get('retrieved', 'unknown')}). On a Pro/Max/Team subscription you are not billed per "
             "token; read this as what the same usage would cost at API prices.")
    L.append("")
    # ---- configuration that shapes token count
    reads, writes = tot["cache_read"], tot["cache_creation"]
    w5, w1 = tot["c5m"], tot["c1h"]
    w5 += max(0, writes - w5 - w1)  # writes without a TTL split are assumed to be 5-minute
    off_flags = [k for k, v in env.items()
                 if k.startswith("DISABLE_PROMPT_CACHING") and str(v).strip().lower() not in ("", "0", "false", "no", "off")]
    if off_flags:
        cache_status = f"disabled by `{', '.join(off_flags)}`"
        if reads + writes:
            cache_status += " (cache tokens were still reported: check which setting wins)"
    elif reads + writes:
        cache_status = "enabled (cache activity observed)"
    else:
        cache_status = "no cache activity observed (disabled, or the window was too short to write a cache)"
    denom = reads + writes + tot["input"]
    effective = tot["input"] + 1.25 * w5 + 2.0 * w1 + 0.1 * reads
    nocache = tot["input"] + writes + reads
    L.append("## Configuration and caching")
    L.append("")
    L.append(f"- **Prompt caching:** {cache_status}")
    if writes:
        if tot["c5m"] or tot["c1h"]:
            L.append(f"- **Cache TTL used (writes):** 5-minute {fmt(tot['c5m'])}, 1-hour {fmt(tot['c1h'])}")
        else:
            L.append("- **Cache TTL used (writes):** not reported in usage; treated as 5-minute below")
    if denom:
        L.append(f"- **Cache hit rate:** {100 * reads / denom:.0f}% of input-side tokens were served from cache")
    if cost_info["priced"] and not cost_info["unpriced"] and cost_info["input_side_uncached"]:
        a, b = cost_info["input_side"], cost_info["input_side_uncached"]
        L.append(f"- **Input-side cost, with vs without caching:** {usd(a)} vs {usd(b)} "
                 f"({100 * (1 - a / b):.0f}% lower; output excluded)")
    elif nocache:
        L.append(f"- **Input-side tokens, effective vs uncached (generic 1.25x/2x/0.1x multipliers, "
                 f"model prices unavailable):** {fmt(round(effective))} vs {fmt(nocache)} "
                 f"({100 * (1 - effective / nocache):.0f}% lower; output excluded)")
    if tot["think_msgs"]:
        L.append(f"- **Thinking:** {tot['think_msgs']} of {len(seen)} assistant message(s) contained thinking blocks "
                 "(thinking tokens are billed as output and are not reported separately)")
    elif any("thinking_blocks" in r for r in window):
        L.append("- **Thinking:** no thinking blocks seen in this window")
    else:
        L.append("- **Thinking:** not recorded (older entries)")
    L.append(f"- **Claude Code version:** {', '.join(versions) if versions else 'not recorded'}"
             f"   **Branch:** {', '.join(branches) if branches else 'not recorded'}"
             f"   **Service tier:** {', '.join(tiers) if tiers else 'not recorded'}")
    if env:
        L.append("- **Token-related environment settings:** " + ", ".join(f"`{k}={v}`" for k, v in sorted(env.items())))
    else:
        L.append("- **Token-related environment settings:** none set (defaults apply; settings.json-only keys such as "
                 "`promptCacheTtl` or `effortLevel` are not visible to the hook)")
    L.append("")
    L.append("## Other factors")
    L.append("")
    L.append(f"- **Subagent tool calls:** " + (", ".join(f"{k} ×{n}" for k, n in sorted(sub_calls.items())) if sub_calls else "none"))
    L.append(f"- **Web search/fetch requests (server-side):** {tot['web']}")
    if compactions:
        L.append("- **Possible compaction or clear** (context dropped sharply): " +
                 "; ".join(f"+{dur(o)}: {fmt(a)} → {fmt(b)}" for o, a, b in compactions))
    else:
        L.append("- **Possible compaction or clear:** none detected")
    L.append("")
    L.append("## Skills flow")
    L.append("")
    if steps:
        L.extend(mermaid_skill_flow(steps, runs, total))
        L.append("")
        L.append("| # | Offset | Skill | Calls | ~Context added | Time until next skill |")
        L.append("|---|--------|-------|-------|----------------|-----------------------|")
        for i, st in enumerate(steps, 1):
            L.append(f"| {i} | +{dur(st['at'])} | {st['name']} | {st['calls']} | ~{fmt(st['added'])} | {dur(st['time'])} |")
        L.append("")
        L.append("**Main skills** (by context added):")
        L.append("")
        for n, p in sorted(per_skill.items(), key=lambda kv: -kv[1]["added"])[:5]:
            L.append(f"- {n}: {p['calls']} call(s) in {p['steps']} step(s), ~{fmt(p['added'])} tokens of context, "
                     f"{dur(p['time'])} of window time")
    else:
        L.append("No skills were used in this window.")
    L.append("")
    L.append("## Tool flow")
    L.append("")
    if runs:
        L.extend(mermaid_tool_flow(runs))
        L.append("")
        shown = flow[:40]
        L.append("In words: " + " → ".join(l if n == 1 else f"{l} ×{n}" for l, n in shown)
                 + (" → …" if len(flow) > 40 else ""))
        L.append("")
        L.append("| # | Offset | Step | Calls | Duration | Context change | Output tokens |")
        L.append("|---|--------|------|-------|----------|----------------|---------------|")
        for i, r in enumerate(runs[:30], 1):
            sign = "+" if r["ctx_delta"] >= 0 else "-"
            L.append(f"| {i} | +{dur(r['at'])} | {r['label']} | {r['calls']} | {dur(r['dur'])} | "
                     f"{sign}{fmt(abs(r['ctx_delta']))} | {fmt(r['out'])} |")
        if len(runs) > 30:
            L.append(f"| … | | {len(runs) - 30} more step(s) not shown | | | | |")
        L.append("")
        L.append("_Duration runs until the next step starts, so it includes your own pauses. Context change is the "
                 "growth in context between this step and the next (negative after a compaction)._")
    else:
        L.append("No tool calls.")
    L.append("")
    if tools:
        L.append("| Tool | Calls | Share |")
        L.append("|------|-------|-------|")
        for t, n in sorted(tools.items(), key=lambda kv: -kv[1]):
            L.append(f"| {t} | {n} | {100 * n / ncalls:.0f}% |")
        L.append("")
    L.append("## Optimization suggestions")
    L.append("")
    tips = advice.suggest(ctx, usd, dur, fmt, seq_text)
    if tips:
        for i, (pri, title, ev, act) in enumerate(tips, 1):
            L.append(f"{i}. **[{pri}] {title}.** {ev}")
            L.append(f"   - *What to do:* {act}")
        L.append("")
        L.append("_These are heuristics from this one window; apply the ones that fit your workflow._")
    else:
        L.append("No obvious waste found in this window: no cache expiry, model switch, compaction, oversized "
                 "tool output or heavy skill was detected.")
    L.append("")
    L.append("## Notes")
    L.append("")
    L.append("- Token counts come from the session transcript `usage` fields, so they are exact. "
             "A message is counted once even if it issued several tool calls.")
    L.append("- Per-skill context is approximate: it is the jump in context size after the skill was called "
             "and also includes anything else that entered the context at that step.")
    L.append(f"- Active time sums gaps between logged events of at most {IDLE_GAP // 60} minutes; longer gaps count as idle. "
             "Timestamps have one-second resolution.")
    L.append("- Cost is an estimate from list prices, priced per message with that message's own model (cache "
             "write and read rates differ by model). It excludes fast mode, data-residency or batch multipliers, "
             "server-side web tool fees and any usage that is not in this session's transcript, so treat it as "
             "approximate, not a bill.")
    L.append("- Effort level, model and mode are sampled when each tool call is logged, so a change shows up at the "
             "next logged call. Env settings are only those visible to the hook process.")
    L.append("- The turn that issues the end command is not included.")
    text = "\n".join(L) + "\n"

    print(text)
    if save:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        path = REPORT_DIR / f"{safe}-{start:%Y%m%d-%H%M%S}.md"
        path.write_text(text, encoding="utf-8")
        print(f"Saved: {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=1)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--session")
    ap.add_argument("--all-sessions", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mark", choices=["start", "end"], help="write a start/end marker")
    ap.add_argument("--span", action="store_true", help="report tokens consumed between marks")
    ap.add_argument("--name", default="", help="marker name (default: 'default')")
    ap.add_argument("--report", action="store_true", help="full markdown report for a window")
    ap.add_argument("--no-save", action="store_true", help="with --report: do not write the .md file")
    a = ap.parse_args()
    name = a.name.strip() or "default"

    rows = load()
    if not rows:
        sys.exit("Log is empty.")

    if a.mark:
        add_mark(rows, a.mark, name)
        if a.mark == "end":
            span(load(), name)
        return
    if a.span:
        span(rows, name)
        return
    if a.report:
        report(rows, name, save=not a.no_save)
        return

    rows = [r for r in rows if not is_mark(r)]
    if not rows:
        sys.exit("Log has only markers, no usage entries yet.")
    if not a.all_sessions:
        sid = a.session or rows[-1].get("session_id")
        rows = [r for r in rows if r.get("session_id") == sid]
        if not rows:
            sys.exit(f"No entries for session {sid}.")

    if a.summary:
        summary(rows)
        return
    picked = rows[-a.last:]
    if a.json:
        print(json.dumps(picked, ensure_ascii=False, indent=2))
    else:
        show_rows(picked)


if __name__ == "__main__":
    main()
