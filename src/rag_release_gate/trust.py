"""The authority policy — one pure function, no key, no network, no I/O.

This is the trust table from `PLAN.md` made executable:

| `authority`     | `may_ground` | `may_cite_for_policy_claim` | `framing`        |
|-----------------|--------------|-----------------------------|------------------|
| `authoritative` | True         | True                        | `current`        |
| `supporting`    | True         | False                       | `supplementary`  |
| `historical`    | False        | False                       | `superseded`     |
| `untrusted`     | False        | False                       | `untrusted_data` |

`historical` and `untrusted` chunks may still be *retrieved* and *rendered* —
that is the point of keeping the archived policy and the planted review in the
context rather than filtering them out. They may be named ("the 2024 policy,
now superseded") or quoted ("one reviewer wrote..."). They may not be the
thing a claim rests on.

`authority` is the only input to the decision. `document_type` and `status` are
recorded and rendered but never change the answer — `test_trust_policy.py`
sweeps all 40 combinations to keep that a checked fact rather than a comment.

Consumers: T08's context builder (`framing` chooses the rendering, and
`untrusted_data` is what triggers the delimiter), T09's CLI sources table,
T13's assertion that no policy or specification claim is cited to an
`untrusted` document.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from rag_release_gate.models import SourceTrust

Framing = Literal["current", "supplementary", "superseded", "untrusted_data"]


class TrustDecision(BaseModel):
    """What a retrieved chunk is allowed to do."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    may_ground: bool
    may_cite_for_policy_claim: bool
    framing: Framing


def decide(source: SourceTrust) -> TrustDecision:
    """Return what `source` may do in an answer.

    Takes `SourceTrust`, so a `CorpusDoc`, `Chunk` or `RetrievedChunk` can be
    passed directly — they all inherit it.
    """
    match source.authority:
        case "authoritative":
            return TrustDecision(
                may_ground=True, may_cite_for_policy_claim=True, framing="current"
            )
        case "supporting":
            return TrustDecision(
                may_ground=True, may_cite_for_policy_claim=False, framing="supplementary"
            )
        case "historical":
            return TrustDecision(
                may_ground=False, may_cite_for_policy_claim=False, framing="superseded"
            )
        case "untrusted":
            return TrustDecision(
                may_ground=False, may_cite_for_policy_claim=False, framing="untrusted_data"
            )
        case unknown:
            # Unreachable while `Authority` is a closed Literal — which is the
            # point. A fifth value has to land here and be decided on purpose.
            raise ValueError(f"no trust decision defined for authority={unknown!r}")
