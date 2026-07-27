"""Probe 4 — does response_format with a JSON Schema work on OpenRouter?

Asked of BOTH pinned chat models. The answer decides whether judge.py needs
`instructor` (a client-side validate-and-retry loop) or can rely on
provider-enforced constrained decoding.

The schema deliberately mirrors the shape DeepEval actually asks a judge for:
a list of per-claim verdicts, not a score. That is the real workload.

"The SDK didn't raise" is NOT the pass condition. A provider can accept the
parameter and ignore it. Pass = the content parses AND validates.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ValidationError

from _common import CANDIDATE, JUDGE, client, rule, show, usage_dict


class Verdict(BaseModel):
    verdict: Literal["yes", "no", "idk"]
    reason: str


class Verdicts(BaseModel):
    verdicts: list[Verdict]


JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "verdicts",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "verdict": {"type": "string", "enum": ["yes", "no", "idk"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["verdict", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["verdicts"],
            "additionalProperties": False,
        },
    },
}

PROMPT = (
    "Context: The Tidepool & Tail return window is 30 days from delivery.\n"
    "Claims: (1) Returns are accepted for 30 days. (2) Shipping is free.\n"
    "For each claim, is it supported by the context? Answer yes, no, or idk."
)

results: dict[str, str] = {}

for model in (CANDIDATE, JUDGE):
    rule(f"PROBE 4 — response_format json_schema on {model}")
    try:
        resp = client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT}],
            response_format=JSON_SCHEMA,
            max_tokens=400,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 — a spike wants the raw failure text
        show("REQUEST FAILED", f"{type(exc).__name__}: {exc}")
        results[model] = "request rejected"
        continue

    content = resp.choices[0].message.content
    show("echoed model", resp.model)
    show("raw content ", content)
    show("cost        ", usage_dict(resp.usage).get("cost", "<absent>"))

    try:
        parsed = Verdicts.model_validate(json.loads(content or ""))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        show("PARSE/VALIDATE FAILED", f"{type(exc).__name__}: {exc}")
        results[model] = "accepted but output did not validate"
        continue

    show("validated   ", f"{len(parsed.verdicts)} verdicts, typed")
    results[model] = "WORKS — provider-enforced schema honoured"

rule("PROBE 4 SUMMARY")
for model, verdict in results.items():
    print(f"  {model:<32} {verdict}")
print(
    "\nIf both say WORKS -> judge.py does NOT need instructor.\n"
    "Add instructor only if a pinned model's compliance actually proves\n"
    "unreliable — not on speculation."
)
