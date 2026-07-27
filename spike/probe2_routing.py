"""Probe 2 — what does the echoed `model` field actually mean?

Raw HTTP on purpose: the SDK's typed models hide fields OpenRouter adds. We
want the unmodified envelope.

The experiment needs a request whose routing is *distinguishable* from the slug
we typed, otherwise both hypotheses predict the same observation:

  openrouter/auto        — a router alias. It cannot serve tokens itself, so
                           something concrete must have run.
  ...:floor              — a routing-variant suffix on a normal slug.
  openai/gpt-4o-mini     — control.
  anthropic/claude-...   — the judge slug, so there is a log entry to compare.

World (i): the field is a verbatim echo of the request.
World (ii): the field reports the model that actually served the request.

Gate item 2 is settled by comparing the printed generation IDs against the
OpenRouter activity log — not by this script's guess.
"""

from __future__ import annotations

import httpx

from _common import BASE_URL, CANDIDATE, JUDGE, headers, rule, show

REQUESTS = [
    ("openrouter/auto", "router alias — cannot itself serve tokens"),
    (f"{CANDIDATE}:floor", "routing-variant suffix"),
    (CANDIDATE, "control — candidate slug"),
    (JUDGE, "control — judge slug"),
]

rule("PROBE 2 — echoed `model` semantics")

rows = []
with httpx.Client(timeout=60) as http:
    for slug, why in REQUESTS:
        print(f"\n--- requesting {slug!r}  ({why})")
        r = http.post(
            f"{BASE_URL}/chat/completions",
            headers=headers(),
            json={
                "model": slug,
                "messages": [{"role": "user", "content": "Reply with exactly one word: pong"}],
                "max_tokens": 8,
                "temperature": 0,
            },
        )
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}: {r.text[:300]}")
            rows.append((slug, f"<HTTP {r.status_code}>", "-", "-"))
            continue

        body = r.json()
        echoed = body.get("model")
        provider = body.get("provider", "<absent>")
        gen_id = body.get("id")
        cost = (body.get("usage") or {}).get("cost", "<absent>")

        show("    echoed model ", echoed)
        show("    provider     ", provider)
        show("    generation id", gen_id)
        show("    usage.cost   ", cost)
        show("    top-level keys", sorted(body.keys()))
        rows.append((slug, echoed, provider, gen_id))

rule("SUMMARY — requested vs echoed")
for slug, echoed, provider, gen_id in rows:
    match = "SAME" if slug == echoed else "DIFFERENT"
    print(f"  {slug:<34} -> {str(echoed):<34} [{match}]  provider={provider}  {gen_id}")

print(
    "\nNext, by hand — this is the part the script cannot do:\n"
    "  1. Open https://openrouter.ai/activity\n"
    "  2. Find each generation ID above.\n"
    "  3. Compare the model the log attributes it to against 'echoed'.\n"
    "\n"
    "  If openrouter/auto echoed back 'openrouter/auto' while the log names a\n"
    "  concrete model  -> world (i), verbatim echo. model_reported is a\n"
    "  CONFIGURATION GUARD only, and EVALUATION.md must say so.\n"
    "  If it echoed the concrete model that served it -> world (ii), and the\n"
    "  field carries real routing evidence.\n"
)
