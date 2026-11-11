"""Cost estimation for the token log: list prices per model, no network needed.

Prices live in ../pricing.json (override with CLAUDE_TOKEN_PRICING). Cache write
and read prices differ by model, so each assistant message is priced with its own
model's rates. Haiku 5.5 uses a higher rate set when the prompt exceeds 100K tokens.
"""
import json
import os
from collections import defaultdict
from pathlib import Path

DEFAULT_PRICING = Path(__file__).resolve().parent.parent / "pricing.json"


def load_pricing():
    path = Path(os.environ.get("CLAUDE_TOKEN_PRICING", DEFAULT_PRICING))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("models", {})
        data.setdefault("meta", {})
        return data
    except (OSError, json.JSONDecodeError):
        return {"models": {}, "meta": {"error": f"could not read {path}"}}


def find_model(pricing, model_id):
    """Longest pricing key that is a prefix of the model id, or None."""
    if not model_id:
        return None
    best = None
    for key in pricing["models"]:
        if model_id.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return best


def rates(pricing, key, prompt_tokens):
    m = pricing["models"][key]
    if m.get("long") and prompt_tokens > m.get("long_over", 100000):
        return m["long"]
    return m


def price(pricing, row, key=None):
    """USD cost parts for one assistant message, or None if the model has no price."""
    key = key or find_model(pricing, row.get("model"))
    if not key:
        return None
    r = rates(pricing, key, row["context_tokens"])
    w5 = row.get("cache_5m_tokens") or 0
    w1 = row.get("cache_1h_tokens") or 0
    w5 += max(0, row["cache_creation_tokens"] - w5 - w1)  # unsplit writes count as 5-minute
    p = {
        "input": row["input_tokens"] * r["in"] / 1e6,
        "cache_write": (w5 * r["cw5"] + w1 * r["cw1"]) / 1e6,
        "cache_read": row["cache_read_tokens"] * r["read"] / 1e6,
        "output": row["output_tokens"] * r["out"] / 1e6,
    }
    p["total"] = p["input"] + p["cache_write"] + p["cache_read"] + p["output"]
    p["input_side_uncached"] = (row["input_tokens"] + row["cache_creation_tokens"]
                                + row["cache_read_tokens"]) * r["in"] / 1e6
    return p


def summarize(pricing, rows):
    """Price every message row; rows with unknown models are listed, not guessed."""
    out = {"parts": defaultdict(float), "by_model": {}, "priced": 0, "unpriced": 0,
           "unpriced_models": [], "input_side": 0.0, "input_side_uncached": 0.0, "per_row": []}
    for r in rows:
        key = find_model(pricing, r.get("model"))
        p = price(pricing, r, key) if key else None
        if p is None:
            out["unpriced"] += 1
            m = r.get("model") or "(model not recorded)"
            if m not in out["unpriced_models"]:
                out["unpriced_models"].append(m)
            out["per_row"].append(None)
            continue
        out["priced"] += 1
        for k in ("input", "cache_write", "cache_read", "output", "total"):
            out["parts"][k] += p[k]
        out["input_side"] += p["input"] + p["cache_write"] + p["cache_read"]
        out["input_side_uncached"] += p["input_side_uncached"]
        bm = out["by_model"].setdefault(key, {"messages": 0, "cost": 0.0})
        bm["messages"] += 1
        bm["cost"] += p["total"]
        out["per_row"].append(p)
    return out


def whatif(pricing, rows, key):
    """Total cost of the already-priced rows if they had run on model `key`."""
    if key not in pricing["models"]:
        return None
    total = 0.0
    for r in rows:
        if find_model(pricing, r.get("model")):
            total += price(pricing, r, key)["total"]
    return total


def usd(x):
    if x >= 1:
        return f"${x:,.2f}"
    if x >= 0.01:
        return f"${x:.3f}"
    return f"${x:.4f}"
