# T01 — Spike findings

**Date:** 2026-07-26 · **Elapsed:** well inside the 2.5h timebox · **Spend:** ~$0.011 (gate: < $0.10)

Throwaway probes in `spike/`. Nothing here graduates to `src/`.

---

## Gate results — all five

| # | Gate | Result |
|---|---|---|
| 1 | `usage.cost` is a real non-zero figure off the completion | **PASS** — `3.9e-06`, plus `cost_details.upstream_inference_cost` |
| 2 | State in one sentence what `model` represents, backed by log comparison | **PASS** — see verbatim finding below |
| 3 | Embeddings returns a vector, dimension known, cost behaviour known | **PASS** — 1536 dims, **cost IS reported** (`2e-07`) |
| 4 | The metric returns a score | **PASS** — Faithfulness `0.5`, correct reason |
| 5 | Judge identity confirmed by external evidence | **PASS** — all 4 judge calls attributed to Anthropic Haiku by the provider's own generation records |

---

## Finding 1 (verbatim, as the ticket requires) — what `model` on the response means

> **On OpenRouter, the `model` field on a chat completion is not a verbatim echo of the requested slug: it reports the model that actually served the request, normalized to an undated OpenRouter slug. A routing alias resolves to a concrete model in the echo, and a routing-variant suffix is stripped.**

Evidence — `probe2_routing.py`, four requests:

| Requested | Echoed `model` | `provider` (top-level) |
|---|---|---|
| `openrouter/auto` | **`openai/gpt-5.6-sol`** | OpenAI |
| `openai/gpt-4o-mini:floor` | **`openai/gpt-4o-mini`** | Azure |
| `openai/gpt-4o-mini` | `openai/gpt-4o-mini` | Azure |
| `anthropic/claude-haiku-4.5` | `anthropic/claude-haiku-4.5` | Amazon Bedrock |

The `openrouter/auto` row is what settles it. A router alias cannot serve tokens itself, so if the field were a verbatim echo it would have returned `openrouter/auto`. It returned a concrete model instead. The `:floor` row shows the same resolution behaviour on a normal slug.

**This is world (ii), with one important qualification about granularity.** There are three identity surfaces and they do **not** agree as strings:

| Surface | Value for the judge call | Notes |
|---|---|---|
| requested slug (`config.py`) | `anthropic/claude-haiku-4.5` | what we asked for |
| response `model` | `anthropic/claude-haiku-4.5` | resolved, **undated** |
| generation record `model` | `anthropic/claude-4.5-haiku-20251001` | canonical, **dated, different word order** |
| generation record `provider_name` | `Amazon Bedrock` | upstream that ran it |

**Consequence for the T15 judge-identity assertion — this is the load-bearing part:**

- `model_reported == model_requested` is a **valid runtime assertion** for concretely-pinned slugs, and it is now more than a configuration guard: the field resolves, so a silent swap to a different model would change it. It still does **not** identify the upstream provider or the dated model version.
- **Do not assert string equality against the generation record.** `anthropic/claude-haiku-4.5` != `anthropic/claude-4.5-haiku-20251001`. Any check against that surface must be a family/substring check plus a recorded exact value, never `==`.
- Record `provider` (top-level, e.g. `Amazon Bedrock`) in `CallRecord`. It is free evidence and it is the only field that names the upstream. **Note the judge runs on Amazon Bedrock — `EVALUATION.md` should say "Anthropic Claude Haiku 4.5, served via Amazon Bedrock", because a reviewer who checks the log will see Bedrock and should not be surprised.**

## Finding 2 — embeddings

`POST /api/v1/embeddings` with `openai/text-embedding-3-small`:

- **dimension 1536**
- **cost IS reported**: `usage.cost = 2e-07`, with `cost_details`, and a generation ID (`gen-emb-...`). The plan assumed this was unknown; it is answered — ingest can report **measured** embedding cost.
- **Trap:** the echoed model is **`text-embedding-3-small`**, *without* the `openai/` prefix — unlike chat, which echoes the full slug. `assert model_reported == model_requested` **would fail for embeddings**. T05 must compare with the prefix stripped, or just record the value.

## Finding 3 — structured output

`response_format` with a JSON Schema **works on both pinned chat models**. Content parsed and validated against a Pydantic model on both.

| Model | Result |
|---|---|
| `openai/gpt-4o-mini` | works — schema honoured |
| `anthropic/claude-haiku-4.5` | works — schema honoured |

**Decision: `judge.py` does NOT need `instructor`.** Do not add it in T02.

## Finding 4 — DeepEval routing: **PLAN.md premise 4 is out of date**

The plan states `OpenRouterModel` "is not wired into `is_native_model()` or `initialize_model()`". **In `deepeval 4.1.3` it is wired into both.** It is now a `DeepEvalOpenAICompatibleModel` subclass that reads `OPENROUTER_API_KEY` and defaults `base_url` to `https://openrouter.ai/api/v1`. Issue #2626 described 4.0.x behaviour.

**Path (a) is PROVEN.** Path (b) was never needed and `litellm` is not installed.

**Path (c) was then also run**, because the choice of path for T15 turned on a question (a) could not answer — see "the provenance trade-off" below.

```
judge class        : OpenRouterModel
get_model_name()   : anthropic/claude-haiku-4.5 (OpenRouter)
using_native_model : True
score              : 0.5   (one supported claim, one contradicted — a correct 0.5)
evaluation_cost    : 0.003253
```

**Judge calls per metric: 4.** One `FaithfulnessMetric` on one test case made four chat completions — truths extraction, claims extraction, verdicts, reason. Every one requested `anthropic/claude-haiku-4.5` and every one was served by Amazon Bedrock.

This confirms the plan's per-call `CallRecord` design: a single ID per case would have collapsed four distinct judge calls into one and made partial routing failure invisible.

**Cost model validated:** the four measured `usage.cost` values sum to `0.003253`, **exactly** DeepEval's reported `evaluation_cost`. The two accounting paths agree.

### The provenance trade-off — why T15 uses the adapter anyway

Path (a) routes correctly, but metric-driven judge calls go through `generate_with_schema()`, which returns `(result, cost)` and nothing more. **The native path never surfaces `generation_id`, `provider`, or a per-call cost breakdown** — those live on the raw completion inside the framework. This spike only saw them by monkey-patching the OpenAI SDK. That is fine for a probe and does not belong in `src/`.

This project's hard rule is *every model call gets its own `CallRecord` with its own `generation_id`*. Under (a), honouring it means intercepting below DeepEval. Under (c), it is free.

Path (c) result — same test case, same judge:

| | path (a) native | path (c) adapter |
|---|---|---|
| score | 0.5 | 0.5 (identical) |
| judge calls | 4 | 4 |
| per-call cost | identical | identical |
| `using_native_model` | `True` | `False` |
| `metric.evaluation_cost` | `0.003253` | **`None`** |
| per-call `generation_id` / `provider` | not exposed | **yours by construction** |

**Decision: T15 builds the custom `DeepEvalBaseLLM` adapter** — chosen for per-call provenance, *not* because the native path failed. The plan's original recommendation survives; its stated reason does not.

**Consequence T15 must handle:** on the adapter path DeepEval accrues no cost, so `evaluation_cost` is `None`. Judge cost is the sum of your own `CallRecord.cost_usd`. **Record `None` as `null`, never as `0`.**

The adapter used `response_format` JSON Schema built from `schema.model_json_schema()` with `strict: False`, and DeepEval's own nested schemas validated on the first attempt — no retry loop, no `instructor`.

## Finding 5 — the evidence, and how it was obtained

Three independent layers, deliberately, because a printed score proves nothing:

1. **Negative control.** `OPENAI_API_KEY` was set to `sk-INVALID-negative-control-T01` before deepeval was imported. The metric scored normally — so nothing fell back to OpenAI. Had it fallen back, it would have failed loudly instead of printing a plausible number.
2. **In-process spy** (`probe5_deepeval.py`) on `Completions.create` **and** `AsyncCompletions.create` — deepeval's schema path is async even with `async_mode=False`, which is why the first run recorded 0 calls. Captured requested slug, reported model, provider, generation ID, tokens and cost per call.
3. **Provider-side records** (`probe6_verify.py`, `GET /api/v1/generation?id=`) — written by OpenRouter's accounting, not by our process. All four judge generation IDs:

```
gen-1785043865-JUmRLKXTModE4PWBSXTj  anthropic/claude-4.5-haiku-20251001  Amazon Bedrock  $0.000703
gen-1785043867-X3UEZiLMf9p5SQkVydCK  anthropic/claude-4.5-haiku-20251001  Amazon Bedrock  $0.000689
gen-1785043869-w0ITu3MtXK8qiPmywsiA  anthropic/claude-4.5-haiku-20251001  Amazon Bedrock  $0.001093
gen-1785043871-iROncFVkHI3zJvabmiig  anthropic/claude-4.5-haiku-20251001  Amazon Bedrock  $0.000768
```

**No OpenAI model appears anywhere in the judge path. The cross-family judge is real.**

**Token-count trap:** the response's `usage.prompt_tokens` (493) equals the record's `native_tokens_prompt` (493), **not** its `tokens_prompt` (304) — the latter is OpenRouter's normalized GPT-tokenizer count. Costs agree exactly; token counts do not. **Reconcile cost, never tokens.**

---

## Pinned versions (working set)

```
python      3.12.13     (uv-managed)
uv          0.11.32
openai      2.48.0
deepeval    4.1.3
pydantic    2.13.4
httpx       0.28.1
litellm     NOT INSTALLED — path (b) never needed
instructor  NOT NEEDED — see finding 3
```

## Known noise

`RuntimeError: Event loop is closed` from httpx/anyio at interpreter shutdown on Windows, after results print. Cosmetic teardown ordering in deepeval's async client, not a failure. If it survives into `src/`, suppress at the runner boundary — do not let it be mistaken for a provider error by `outcome_class`.

## Decisions this ticket settles

1. **T02:** add `deepeval==4.1.3`. **No `litellm`. No `instructor`.**
2. **T05:** embeddings cost is measured and recorded, not `null`. Strip the `openai/` prefix before any model-identity comparison.
3. **T15:** build the custom `DeepEvalBaseLLM` adapter — for per-call provenance, not because the native path failed. Keep the per-call `CallRecord`; add a `provider` field. Assert `model_reported == model_requested` (valid for pinned slugs) and record `generation_id` + `provider` alongside it. Expect **4 judge calls per Faithfulness metric per case**. Any instrumentation must cover the **async** SDK client — deepeval's schema path is async even with `async_mode=False`, which cost this spike one run that observed zero calls.
4. **T15/EVALUATION.md:** the judge-identity assertion is stronger than the plan's cautious fallback wording allowed — the field resolves rather than echoes — but it still does not prove the dated model version or the upstream. Say exactly that, and name Amazon Bedrock.

## Activity-log verification

The Chrome extension was not connected, so the machine-readable cross-check above used `GET /api/v1/generation` — the same provider-side accounting the activity page renders. **Maria confirmed on 2026-07-26 that the runs are visible in the OpenRouter activity log.** Gate 5's external-evidence requirement is met by the generation records; the activity page is the human-readable view of the same source.

Re-check by hand at T15, when the identity assertion becomes permanent: the count of judge requests in the log must equal `len(judge_calls)` in the run artifact. A mismatch means calls are escaping instrumentation.
