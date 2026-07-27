"""Probe 3 — POST /api/v1/embeddings. Dimension, and does it report cost?

Gate item 3. The cost answer changes only how ingest *reports* cost (T05), never
whether ingest succeeds: absent cost is recorded as null, never as an estimate
and never as a failure.
"""

from __future__ import annotations

import httpx

from _common import BASE_URL, EMBED, client, headers, rule, show, usage_dict

rule("PROBE 3 — embeddings via the SDK")

resp = client().embeddings.create(
    model=EMBED,
    input="What is the Tidepool & Tail return window?",
)
vec = resp.data[0].embedding

show("model requested", EMBED)
show("model echoed   ", resp.model)
show("vector dim     ", len(vec))
show("first 4 floats ", [round(f, 6) for f in vec[:4]])
show("usage          ", usage_dict(resp.usage))

rule("PROBE 3b — same call over raw HTTP (does the envelope carry cost?)")

with httpx.Client(timeout=60) as http:
    r = http.post(
        f"{BASE_URL}/embeddings",
        headers=headers(),
        json={"model": EMBED, "input": "What is the Tidepool & Tail return window?"},
    )
    body = r.json() if r.status_code == 200 else {}
    if r.status_code != 200:
        print(f"HTTP {r.status_code}: {r.text[:300]}")
    else:
        usage = body.get("usage") or {}
        show("top-level keys", sorted(body.keys()))
        show("usage block   ", usage)
        show("usage.cost    ", usage.get("cost", "<ABSENT>"))
        show("generation id ", body.get("id", "<ABSENT>"))

print()
dim = len(vec)
print(f"GATE 3 — vector returned, dimension = {dim}")
print("GATE 3 — cost reported by embeddings endpoint: see 'usage.cost' above")
