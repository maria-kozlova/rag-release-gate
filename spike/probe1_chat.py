"""Probe 1 — OpenAI SDK against OpenRouter. Does usage.cost arrive inline?

Gate item 1: usage.cost prints a real non-zero dollar figure straight off the
completion — no second /api/v1/generation round-trip.
"""

from __future__ import annotations

from _common import CANDIDATE, client, rule, show, usage_dict

rule("PROBE 1 — chat completion via the openai SDK, base_url swapped")

resp = client().chat.completions.create(
    model=CANDIDATE,
    messages=[{"role": "user", "content": "Reply with exactly one word: pong"}],
    max_tokens=10,
    temperature=0,
)

show("model requested", CANDIDATE)
show("model echoed   ", resp.model)
show("generation id  ", resp.id)
show("content        ", resp.choices[0].message.content)

u = usage_dict(resp.usage)
show("usage (full)   ", u)
show("usage.cost     ", u.get("cost", "<ABSENT>"))
show("cost_details   ", u.get("cost_details", "<ABSENT>"))

# Top-level extras OpenRouter adds beyond the OpenAI schema (e.g. `provider`).
extras = getattr(resp, "model_extra", None) or {}
show("top-level extras", {k: v for k, v in extras.items()})

print()
cost = u.get("cost")
if isinstance(cost, (int, float)) and cost > 0:
    print(f"GATE 1 PASS — measured cost ${cost:.8f} on the completion itself")
else:
    print(f"GATE 1 FAIL — usage.cost is {cost!r}, not a positive dollar figure")
