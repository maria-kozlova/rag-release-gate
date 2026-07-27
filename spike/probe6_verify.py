"""Probe 6 — cross-check generation IDs against OpenRouter's own record.

GET /api/v1/generation?id=<gen_id> reads the provider's stored record for a
completed generation. That record is written by OpenRouter's accounting, not
by the response our process parsed — so it is the same underlying source the
activity page renders.

This is NOT a substitute for gate 5's activity-log check by hand. It is the
machine-readable half of the same evidence, and it settles probe 2 by naming
what actually served `openrouter/auto`.

Usage: uv run python probe6_verify.py <gen-id> [<gen-id> ...]
"""

from __future__ import annotations

import sys
import time

import httpx

from _common import BASE_URL, headers, rule, show

FIELDS = (
    "model",
    "provider_name",
    "origin",
    "total_cost",
    "usage",
    "tokens_prompt",
    "tokens_completion",
    "native_tokens_prompt",
    "native_tokens_completion",
    "created_at",
)


def fetch(http: httpx.Client, gen_id: str, tries: int = 4) -> dict | None:
    """The generation store indexes asynchronously — retry before concluding."""
    for attempt in range(tries):
        r = http.get(f"{BASE_URL}/generation", headers=headers(), params={"id": gen_id})
        if r.status_code == 200:
            return r.json().get("data", {})
        if attempt < tries - 1:
            time.sleep(2 * (attempt + 1))
    print(f"    HTTP {r.status_code}: {r.text[:200]}")
    return None


def main() -> None:
    ids = sys.argv[1:]
    if not ids:
        sys.exit("pass one or more generation IDs")

    rule("PROBE 6 — provider-side generation records")
    with httpx.Client(timeout=60) as http:
        for gen_id in ids:
            print(f"\n--- {gen_id}")
            data = fetch(http, gen_id)
            if data is None:
                continue
            for f in FIELDS:
                if f in data:
                    show(f"    {f:<18}", data[f])


if __name__ == "__main__":
    main()
