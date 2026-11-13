"""Time and estimated token cost of one Generate job.

    summarize(records, seconds) -> {"seconds", "calls", "input", "cached", "output", "cost_usd", "priced", "by_model"}
    describe(summary) -> one status line, e.g.
        "Took 3 min 40 s · 10 Codex calls · 246K tokens in (82K cached), 54K out · about $0.40 at API prices"

records come from codex_client.take_usage(): [{model, input, cached, output}], where input includes cached.
PRICES are USD per 1M tokens (input, cached input, output) from public API price lists, 2026-11. With a ChatGPT
sign-in Codex uses the plan's allowance instead, so the dollar figure is what the same tokens would cost on the
API: an estimate for comparing jobs, not a bill. Models missing here are counted in tokens but not priced.
"""

PRICES = {
    "gpt-6-astra": (10.00, 1.00, 50.00),
    "gpt-6.1-terra": (1.00, 0.05, 5.00),
    "gpt-6-luna": (0.10, 0.01, 0.50),
}


def summarize(records: list[dict], seconds: float) -> dict:
    by_model, cost, priced = {}, 0.0, True
    for r in records:
        m = by_model.setdefault(r["model"], {"calls": 0, "input": 0, "cached": 0, "output": 0})
        m["calls"] += 1
        for key in ("input", "cached", "output"):
            m[key] += r[key]
    for model, m in by_model.items():
        price = PRICES.get(model)
        if price is None:
            priced = False
            continue
        fresh = max(m["input"] - m["cached"], 0)
        m["cost_usd"] = (fresh * price[0] + m["cached"] * price[1] + m["output"] * price[2]) / 1_000_000
        cost += m["cost_usd"]
    total = {key: sum(m[key] for m in by_model.values()) for key in ("calls", "input", "cached", "output")}
    return {"seconds": round(seconds, 1), **total, "cost_usd": round(cost, 4) if records else None,
            "priced": priced and bool(records), "by_model": by_model}


def _duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def _tokens(n: int) -> str:
    return f"{n / 1000:.0f}K" if n >= 10_000 else f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def describe(summary: dict, provider: str = "Codex") -> str:
    parts = [f"Took {_duration(summary['seconds'])}"]
    if not summary["calls"]:
        return parts[0] + f" · token use not reported by {provider}"
    parts.append(f"{summary['calls']} {provider} call{'s' * (summary['calls'] != 1)}")
    cached = f" ({_tokens(summary['cached'])} cached)" if summary["cached"] else ""
    parts.append(f"{_tokens(summary['input'])} tokens in{cached}, {_tokens(summary['output'])} out")
    if summary["cost_usd"] is not None:
        approx = "about" if summary["priced"] else "at least"
        cost = summary["cost_usd"]
        parts.append(f"{approx} ${cost:.3f} at API prices" if cost < 0.01 else f"{approx} ${cost:.2f} at API prices")
    return " · ".join(parts)
