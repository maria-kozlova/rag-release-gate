"""Probe 5 — a real DeepEval FaithfulnessMetric with a cross-family judge.

Gate items 4 and 5. A printed score is NOT the deliverable; evidence about
which model produced it is.

Three defences against "it printed 0.5, therefore it worked":

  1. NEGATIVE CONTROL. OPENAI_API_KEY is set to garbage before the metric runs.
     If anything silently falls back to OpenAI, it must fail loudly instead of
     scoring plausibly. (deepeval issue #2626's failure mode.)

  2. A SPY on the OpenAI SDK's chat-completions entry point, so every judge
     call is recorded with the slug requested, the model the provider reported,
     the generation ID and the measured cost — the CallRecord shape from
     PLAN.md. This also answers "how many judge calls does ONE metric make?".

  3. The generation IDs printed at the end are meant to be looked up by hand in
     https://openrouter.ai/activity. The spy observes our own process; the
     activity log is the provider's independent record. Gate 5 needs both.

The test case is built so a correct judge CANNOT score 1.0: one claim is
supported by the context and one is contradicted by it. A judge that returns a
perfect score is a judge that did not read.

Usage:  uv run python probe5_deepeval.py --path a     (native OpenRouterModel)
        uv run python probe5_deepeval.py --path b     (LiteLLMModel)
        uv run python probe5_deepeval.py --path c     (custom DeepEvalBaseLLM)
"""

from __future__ import annotations

import argparse
import json
import os

from _common import BASE_URL, JUDGE, api_key, rule, show

KEY = api_key()
os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"
# (1) NEGATIVE CONTROL — poison the fallback path before importing deepeval.
os.environ["OPENAI_API_KEY"] = "sk-INVALID-negative-control-T01"

from openai.resources.chat import completions as _chat  # noqa: E402
from pydantic import BaseModel  # noqa: E402

CALLS: list[dict] = []
_orig_create = _chat.Completions.create
_orig_acreate = _chat.AsyncCompletions.create


def _record(self, kwargs: dict, resp) -> None:
    usage = getattr(resp, "usage", None)
    usage_d = usage.model_dump() if usage is not None else {}
    CALLS.append(
        {
            "model_requested": kwargs.get("model"),
            "model_reported": getattr(resp, "model", None),
            "provider": (getattr(resp, "model_extra", None) or {}).get("provider"),
            "generation_id": getattr(resp, "id", None),
            "base_url": str(getattr(getattr(self, "_client", None), "base_url", "?")),
            "tokens_in": usage_d.get("prompt_tokens"),
            "tokens_out": usage_d.get("completion_tokens"),
            "cost_usd": usage_d.get("cost"),
        }
    )


def _spy(self, *args, **kwargs):  # (2) SPY — sync entry point
    resp = _orig_create(self, *args, **kwargs)
    _record(self, kwargs, resp)
    return resp


async def _aspy(self, *args, **kwargs):  # ...and the async one deepeval actually uses
    resp = await _orig_acreate(self, *args, **kwargs)
    _record(self, kwargs, resp)
    return resp


_chat.Completions.create = _spy
_chat.AsyncCompletions.create = _aspy

from deepeval.metrics import FaithfulnessMetric  # noqa: E402
from deepeval.models import DeepEvalBaseLLM  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

CONTEXT = [
    "The Tidepool & Tail return window is 30 days from delivery.",
    "Standard shipping is $6.99 for orders under $50.",
]
ANSWER = (
    "You can return your order within 30 days of delivery, "
    "and shipping is always free on every order."
)


# ---------------------------------------------------------------- path (c)
class OpenRouterJudge(DeepEvalBaseLLM):
    """~40 lines against the documented extension point.

    Non-native path contract (verified in deepeval/metrics/utils.py 4.1.3):
    generate(prompt, schema=SchemaCls) must return an INSTANCE of SchemaCls
    (a raw JSON string is also tolerated). No (result, cost) tuple — that is
    the native path only.
    """

    def __init__(self, model: str = JUDGE):
        self._model = model
        from openai import OpenAI

        self._client = OpenAI(base_url=BASE_URL, api_key=KEY)
        super().__init__(model)

    def load_model(self):
        return self._client

    def get_model_name(self) -> str:
        return self._model

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        kwargs: dict = {}
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": False,
                    "schema": schema.model_json_schema(),
                },
            }
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            **kwargs,
        )
        content = resp.choices[0].message.content or ""
        if schema is None:
            return content
        return schema.model_validate(json.loads(content))

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        return self.generate(prompt, schema)


def build_judge(path: str):
    if path == "a":
        from deepeval.models import OpenRouterModel

        # NOTE: in deepeval 4.1.3 OpenRouterModel IS wired into is_native_model()
        # and initialize_model(). Issue #2626 described 4.0.x. Verify, don't trust.
        return OpenRouterModel(model=JUDGE, api_key=KEY, base_url=BASE_URL)
    if path == "b":
        from deepeval.models import LiteLLMModel

        return LiteLLMModel(
            model=f"openrouter/{JUDGE}", base_url=BASE_URL, api_key=KEY
        )
    if path == "c":
        return OpenRouterJudge()
    raise SystemExit(f"unknown path {path!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", choices=["a", "b", "c"], default="a")
    args = ap.parse_args()

    rule(f"PROBE 5 — FaithfulnessMetric, judge = {JUDGE}, path ({args.path})")

    judge = build_judge(args.path)
    metric = FaithfulnessMetric(model=judge, threshold=0.5, async_mode=False)

    show("judge class     ", type(judge).__name__)
    show("get_model_name()", judge.get_model_name())
    show("using_native_model", metric.using_native_model)
    show("OPENAI_API_KEY  ", os.environ["OPENAI_API_KEY"] + "   <- deliberately invalid")

    metric.measure(
        LLMTestCase(input="What is the return window?", actual_output=ANSWER,
                    retrieval_context=CONTEXT)
    )

    rule("RESULT")
    show("score            ", metric.score)
    show("reason           ", metric.reason)
    show("evaluation_cost  ", metric.evaluation_cost)
    print("\n  (one claim in the answer is supported, one is contradicted —")
    print("   a judge that scores 1.0 did not actually read the context)")

    rule(f"OBSERVED MODEL CALLS — {len(CALLS)} chat completions for ONE metric")
    for i, c in enumerate(CALLS, 1):
        print(f"\n  call {i}")
        for k, v in c.items():
            print(f"    {k:<16} {v}")

    wrong = [c for c in CALLS if c["model_requested"] != JUDGE]
    rule("VERDICT")
    print(f"  judge calls made          : {len(CALLS)}")
    print(f"  calls NOT requesting {JUDGE}: {len(wrong)}")
    if wrong:
        print("  >>> ROUTING FAILURE — some calls went elsewhere:")
        for c in wrong:
            print(f"      {c['model_requested']} @ {c['base_url']}")
    print(
        "\n  Gate 5 is NOT satisfied by the lines above. Open\n"
        "  https://openrouter.ai/activity and confirm these generation IDs are\n"
        f"  attributed to {JUDGE}. The spy watches our process; the activity log\n"
        "  is the provider's independent record."
    )


if __name__ == "__main__":
    main()
