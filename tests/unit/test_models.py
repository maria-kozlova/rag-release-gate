"""Unit checks over the schemas — NOT the release gate. No key, no network.

These tests exist to prove the schemas *reject* things. A model that accepts
everything is documentation, not validation, and this project's whole claim is
that the golden dataset and the trace record are enforced rather than described.

Each test changes exactly one field of a known-good payload, so a failure names
the constraint that stopped biting.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rag_release_gate import config
from rag_release_gate.models import (
    AnswerResult,
    CallRecord,
    CaseTrace,
    Chunk,
    CorpusDoc,
    DeterministicResult,
    GoldenCase,
    JudgeScore,
    MetricSummary,
    Product,
    RetrievedChunk,
    RunArtifact,
    SourceTrust,
    read_jsonl,
    write_jsonl,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


# --------------------------------------------------------------------------
# Known-good payloads. Every test below is one deviation from one of these.
# --------------------------------------------------------------------------


def _corpus_doc(**over: Any) -> dict[str, Any]:
    return {
        "doc_id": "policies/returns-2026",
        "document_type": "policy",
        "status": "active",
        "effective_date": date(2026, 1, 1),
        "authority": "authoritative",
    } | over


def _product(**over: Any) -> dict[str, Any]:
    return {
        "id": "AQ-114",
        "name": "Pearl 40 Rimless Tank",
        "category": "aquatics",
        "price_usd": 189.0,
        "stock": 12,
        "min_tank_size_gal": 40,
        "care_level": "intermediate",
        "safety_notes": None,
    } | over


def _chunk(**over: Any) -> dict[str, Any]:
    return {
        "chunk_id": "policies/returns-2026#0",
        "doc_id": "policies/returns-2026",
        "heading": "Returns window",
        "text": "Items may be returned within 30 days of delivery.",
        "document_type": "policy",
        "status": "active",
        "effective_date": date(2026, 1, 1),
        "authority": "authoritative",
    } | over


def _retrieved_chunk(**over: Any) -> dict[str, Any]:
    return _chunk(score=0.91, rank=0) | over


def _golden_case(**over: Any) -> dict[str, Any]:
    return {
        "id": "G-014",
        "category": "policy",
        "question": "Can I return an opened filter after 3 weeks?",
        "expected_behavior": "answer",
        "reference_answer": "Yes — the returns window is 30 days from delivery.",
        "expected_doc_ids": ["policies/returns-2026"],
        "must_include": ["30 day"],
        "must_not_include": ["14 day"],
        "must_retrieve_doc_ids": ["policies/returns-2024-ARCHIVED"],
        "max_latency_ms": 8000,
        "notes": "Active-vs-archived returns conflict. The archived doc must reach context.",
    } | over


def _call_record(**over: Any) -> dict[str, Any]:
    return {
        "role": "candidate",
        "metric": None,
        "model_requested": config.CANDIDATE_MODEL,
        "model_reported": config.CANDIDATE_MODEL,
        "provider": "OpenAI",
        "generation_id": "gen-1785043865-JUmRLKXTModE4PWBSXTj",
        "tokens_in": 493,
        "tokens_out": 88,
        "cost_usd": 3.9e-06,
        "latency_ms": 1420,
        "outcome_class": "ok",
    } | over


def _null_call_record(**over: Any) -> dict[str, Any]:
    """A call where the provider reported no metadata at all — every nullable
    field genuinely `None`. This is the shape T07 must still accept."""
    return _call_record(
        metric=None,
        model_reported=None,
        provider=None,
        generation_id=None,
        tokens_in=None,
        tokens_out=None,
        cost_usd=None,
    ) | over


def _case_trace(**over: Any) -> dict[str, Any]:
    return {
        "case_id": "G-014",
        "question": "Can I return an opened filter after 3 weeks?",
        "category": "policy",
        "candidate_model": config.CANDIDATE_MODEL,
        "candidate_temperature": 0.0,
        "candidate_max_tokens": None,
        "judge_model": config.JUDGE_MODEL,
        "judge_temperature": 0.0,
        "judge_strict_mode": True,
        "system_prompt_version": "v1",
        "system_prompt_sha256": HASH_A,
        "retrieval_k": 3,
        "retrieved_chunks": [RetrievedChunk(**_retrieved_chunk())],
        "retrieved_context_sha256": HASH_B,
        "index_manifest_sha256": HASH_C,
        "answer": "Returns are accepted within 30 days [policies/returns-2026].",
        "citations": ["policies/returns-2026"],
        "refused": False,
        "outcome_class": "ok",
        "latency_ms": 1420,
        "candidate_calls": [CallRecord(**_call_record())],
        "judge_calls": [],
    } | over


def _run_artifact(**over: Any) -> dict[str, Any]:
    return {
        "run_id": "run-20260730-001",
        "started_at": datetime(2026, 7, 30, 18, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 7, 30, 18, 4, tzinfo=UTC),
        "git_sha": "b7e1a96",
        "scope": "smoke",
        "suite_version": config.SUITE_VERSION,
        "candidate_model": config.CANDIDATE_MODEL,
        "judge_model": config.JUDGE_MODEL,
        "embedding_model": config.EMBEDDING_MODEL,
        "system_prompt_version": "v1",
        "system_prompt_sha256": HASH_A,
        "index_manifest_sha256": HASH_C,
        "retrieval_k": 3,
        "cases": [CaseTrace(**_case_trace())],
        "embedding_calls": [],
        "metric_summaries": [],
        "infra_failure": False,
    } | over


# --------------------------------------------------------------------------
# 1 — the happy path, for every model
# --------------------------------------------------------------------------


def test_every_model_parses_from_a_valid_payload() -> None:
    assert CorpusDoc(**_corpus_doc()).doc_id == "policies/returns-2026"
    assert Product(**_product()).category == "aquatics"
    assert Chunk(**_chunk()).authority == "authoritative"

    retrieved = RetrievedChunk(**_retrieved_chunk())
    assert (retrieved.rank, retrieved.doc_id) == (0, "policies/returns-2026")

    assert GoldenCase(**_golden_case()).expected_behavior == "answer"
    assert CallRecord(**_call_record()).role == "candidate"

    assert DeterministicResult(
        name="cites_returns_2026", passed=True, expected="policies/returns-2026", observed="cited"
    ).passed
    assert JudgeScore(metric="faithfulness", score=0.91, threshold=0.8, reason=None).score == 0.91
    assert MetricSummary(metric="faithfulness", mean=0.91, stdev=0.02, n=3).n == 3

    answer = AnswerResult(
        answer="Returns are accepted within 30 days [policies/returns-2026].",
        citations=["policies/returns-2026"],
        retrieved_chunks=[retrieved],
        retrieved_context_sha256=HASH_B,
        refused=False,
        outcome_class="ok",
        latency_ms=1420,
        candidate_calls=[CallRecord(**_call_record())],
    )
    assert answer.retrieved_doc_ids == ["policies/returns-2026"]

    trace = CaseTrace(**_case_trace())
    assert trace.retrieved_chunk_ids == ["policies/returns-2026#0"]

    run = RunArtifact(**_run_artifact())
    assert run.scope == "smoke"


def test_the_source_trust_block_stands_alone() -> None:
    """`trust.py` (T04) takes this type, and the traceability record's
    per-chunk `source_trust` is this type."""
    trust = SourceTrust(
        document_type="review", status="active", effective_date=date(2026, 3, 2),
        authority="untrusted",
    )
    assert trust.authority == "untrusted"


# --------------------------------------------------------------------------
# 2, 3, 4 — the closed sets are actually closed
# --------------------------------------------------------------------------


def test_an_unknown_category_is_rejected() -> None:
    """A typo'd category is how a case joins a suite that never scores it."""
    with pytest.raises(ValidationError):
        GoldenCase(**_golden_case(category="refusl"))


def test_an_unknown_authority_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CorpusDoc(**_corpus_doc(authority="trusted"))


def test_an_unknown_call_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CallRecord(**_call_record(role="grader"))


def test_the_other_closed_sets_are_closed_too() -> None:
    with pytest.raises(ValidationError):
        CorpusDoc(**_corpus_doc(document_type="blogpost"))
    with pytest.raises(ValidationError):
        CorpusDoc(**_corpus_doc(status="deprecated"))
    with pytest.raises(ValidationError):
        CallRecord(**_call_record(outcome_class="failed"))
    with pytest.raises(ValidationError):
        GoldenCase(**_golden_case(expected_behavior="maybe"))
    with pytest.raises(ValidationError):
        RunArtifact(**_run_artifact(scope="partial"))


# --------------------------------------------------------------------------
# 5, 6 — the refusal rule, and the trap inside it
# --------------------------------------------------------------------------


def test_a_refusal_case_with_a_reference_answer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GoldenCase(
            **_golden_case(
                category="refusal",
                expected_behavior="refuse",
                reference_answer="We do not stock competitor products.",
            )
        )


def test_a_refusal_case_expecting_a_refusal_needs_no_reference_answer() -> None:
    case = GoldenCase(
        **_golden_case(
            category="refusal",
            expected_behavior="refuse",
            reference_answer=None,
            expected_doc_ids=[],
            must_include=[],
        )
    )
    assert case.reference_answer is None


def test_a_false_refusal_guard_case_parses() -> None:
    """The trap this schema had to avoid.

    The plan's category 6 — near-miss in-scope questions that must be ANSWERED,
    which it calls non-negotiable — are `category="refusal"` cases with
    `expected_behavior="answer"` and a real reference answer. They exist so an
    assistant that refuses everything cannot score 100%.

    Had the refusal validator keyed off `category` instead of
    `expected_behavior`, this case would be unrepresentable and the entire
    over-refusal gate would quietly cease to exist. This test is what stops a
    future edit from making that mistake.
    """
    case = GoldenCase(
        **_golden_case(
            id="G-031",
            category="refusal",
            expected_behavior="answer",
            reference_answer="Yes — a 40-gallon tank suits an adult axolotl.",
            notes="False-refusal guard: in-scope and must be answered, not refused.",
        )
    )
    assert (case.category, case.expected_behavior) == ("refusal", "answer")
    assert case.reference_answer is not None


def test_an_answer_case_without_a_reference_answer_is_rejected() -> None:
    """It would otherwise drop silently out of T15's judged scope."""
    with pytest.raises(ValidationError):
        GoldenCase(**_golden_case(expected_behavior="answer", reference_answer=None))


# --------------------------------------------------------------------------
# 7 — the trust table, enforced by the type
# --------------------------------------------------------------------------


def test_an_archived_document_may_not_be_authoritative() -> None:
    with pytest.raises(ValidationError):
        CorpusDoc(**_corpus_doc(status="archived", authority="authoritative"))


def test_an_archived_document_must_be_historical() -> None:
    """Stronger than the T03 gate item, and deliberately so: this is T04's
    corpus rule made a property of the type, so it cannot be forgotten."""
    for authority in ("authoritative", "supporting", "untrusted"):
        with pytest.raises(ValidationError):
            CorpusDoc(**_corpus_doc(status="archived", authority=authority))

    archived = CorpusDoc(
        **_corpus_doc(
            doc_id="policies/returns-2024-ARCHIVED",
            status="archived",
            authority="historical",
            effective_date=date(2024, 1, 1),
        )
    )
    assert archived.authority == "historical"


def test_a_chunk_inherits_the_archived_rule_from_its_document() -> None:
    """Chunks carry copied trust metadata; the copy cannot drift from the table."""
    with pytest.raises(ValidationError):
        Chunk(**_chunk(status="archived", authority="authoritative"))
    with pytest.raises(ValidationError):
        RetrievedChunk(**_retrieved_chunk(status="archived", authority="supporting"))


# --------------------------------------------------------------------------
# 8, 9, 10 — null is valid; an estimate is not
# --------------------------------------------------------------------------


def test_a_call_with_no_provider_metadata_is_valid() -> None:
    """`null` is a first-class value. A provider that reports no cost, no
    model and no token counts still yields a valid record with `outcome_class`
    `ok` — missing metadata is not an error, and never an estimate."""
    record = CallRecord(**_null_call_record())
    assert record.cost_usd is None
    assert record.model_reported is None
    assert record.generation_id is None
    assert (record.tokens_in, record.tokens_out) == (None, None)
    assert record.outcome_class == "ok"


@pytest.mark.parametrize("smuggled", ["estimated", "~0.01", "approx 0.01", ""])
def test_an_obviously_estimated_cost_is_rejected(smuggled: str) -> None:
    with pytest.raises(ValidationError):
        CallRecord(**_call_record(cost_usd=smuggled))


def test_a_numeric_string_cost_is_rejected_too() -> None:
    """The one with real teeth, and the reason this module runs in strict mode.

    `"~0.01"` is rejected by any Pydantic configuration — it does not parse as
    a float. `"0.01"` is different: in Pydantic's default *lax* mode it coerces
    cleanly to `0.01`, and an estimated figure has just entered a field this
    project's README describes as measured, leaving no trace that it did.

    Strict mode is what makes "never label an estimate as measured" a property
    of the type rather than a rule someone has to remember. If this test starts
    failing, `strict=True` has been dropped and every downstream cost claim is
    unenforced.
    """
    with pytest.raises(ValidationError):
        CallRecord(**_call_record(cost_usd="0.01"))

    for field in ("tokens_in", "tokens_out", "latency_ms"):
        with pytest.raises(ValidationError):
            CallRecord(**_call_record(**{field: "493"}))


def test_a_real_measured_cost_is_accepted_in_every_honest_form() -> None:
    """Strictness must not reject a genuine measurement. T01 observed costs as
    small as 2e-07, and an integer zero is a legitimate float value."""
    assert CallRecord(**_call_record(cost_usd=2e-07)).cost_usd == 2e-07
    assert CallRecord(**_call_record(cost_usd=0)).cost_usd == 0


# --------------------------------------------------------------------------
# 11 — model_requested is required for every role
# --------------------------------------------------------------------------


def test_a_call_record_without_a_requested_model_is_rejected() -> None:
    """The gate item asks for this on `role="judge"`. It holds for every role,
    and by the field's type rather than by a validator — `model_requested: str`
    is required and non-nullable, so there is no role for which a call can be
    recorded without saying what was asked for."""
    for role in ("judge", "candidate", "embedding"):
        payload = _call_record(role=role)
        del payload["model_requested"]
        with pytest.raises(ValidationError):
            CallRecord(**payload)

        with pytest.raises(ValidationError):
            CallRecord(**_call_record(role=role, model_requested=None))


def test_model_reported_is_not_forced_to_equal_model_requested() -> None:
    """T01: the embeddings endpoint echoes the model WITHOUT the `openai/`
    prefix. An equality constraint here would fail on a correct system. Judge
    identity is T15's assertion, over `judge_calls`, not the schema's."""
    record = CallRecord(
        **_call_record(
            role="embedding",
            model_requested=config.EMBEDDING_MODEL,
            model_reported=config.EMBEDDING_MODEL_REPORTED,
        )
    )
    assert record.model_reported != record.model_requested


# --------------------------------------------------------------------------
# 12 — lossless JSONL round trip, nulls included
# --------------------------------------------------------------------------


def test_jsonl_round_trips_losslessly_including_every_none(tmp_path: Path) -> None:
    """Equality alone would not catch a default quietly refilling a dropped
    field, so this also reads the raw line and looks for the literal `null`."""
    records = [
        CallRecord(**_call_record()),
        CallRecord(**_null_call_record(role="judge")),
    ]
    path = tmp_path / "calls.jsonl"

    assert write_jsonl(path, records) == 2
    assert read_jsonl(path, CallRecord) == records

    raw = path.read_text(encoding="utf-8").splitlines()[1]
    for nullable in (
        "metric",
        "model_reported",
        "provider",
        "generation_id",
        "tokens_in",
        "tokens_out",
        "cost_usd",
    ):
        assert f'"{nullable}":null' in raw, (
            f"{nullable} did not survive serialization as an explicit null — "
            "a dropped field lets a reader's default fabricate a value"
        )


def test_the_whole_evidence_record_round_trips(tmp_path: Path) -> None:
    """Dates, aware datetimes and nested call lists all survive the trip.

    This is also the test that pins `read_jsonl` to `model_validate_json`:
    under strict mode a `date` is only reconstructible from JSON-mode
    validation, so routing through `json.loads` first would fail here.
    """
    run = RunArtifact(**_run_artifact())
    path = tmp_path / "runs.jsonl"

    write_jsonl(path, [run])
    (restored,) = read_jsonl(path, RunArtifact)

    assert restored == run
    assert restored.cases[0].retrieved_chunks[0].effective_date == date(2026, 1, 1)
    assert restored.started_at.tzinfo is not None

    cases_path = tmp_path / "traces.jsonl"
    write_jsonl(cases_path, run.cases)
    assert read_jsonl(cases_path, CaseTrace) == run.cases


def test_write_jsonl_uses_lf_line_endings(tmp_path: Path) -> None:
    """`.gitattributes` pins `eol=lf` and these bytes feed hashes; Windows
    would otherwise translate to CRLF and change them."""
    path = tmp_path / "calls.jsonl"
    write_jsonl(path, [CallRecord(**_call_record())])
    assert b"\r\n" not in path.read_bytes()


def test_reading_a_malformed_line_names_the_file_and_line_number(tmp_path: Path) -> None:
    """T10 validates every line of `golden.jsonl` against `GoldenCase`. When a
    line is wrong, the failure has to point at the line, not at a traceback."""
    path = tmp_path / "golden.jsonl"
    good = GoldenCase(**_golden_case()).model_dump_json()
    bad = GoldenCase(**_golden_case(id="G-015")).model_dump_json().replace(
        '"category":"policy"', '"category":"refusl"'
    )
    path.write_text(f"{good}\n\n{bad}\n", encoding="utf-8", newline="\n")

    with pytest.raises(ValueError, match=r"golden\.jsonl:3"):
        read_jsonl(path, GoldenCase)


# --------------------------------------------------------------------------
# 13, 14 — forbid and frozen
# --------------------------------------------------------------------------


def test_an_unknown_field_is_rejected() -> None:
    """This is what gives T10's schema test teeth. Without `extra="forbid"`, a
    case written with `must_retreive_doc_ids` parses fine, contributes nothing,
    and its reachability contract silently does not exist."""
    with pytest.raises(ValidationError):
        GoldenCase(**_golden_case(must_retreive_doc_ids=["policies/returns-2026"]))
    with pytest.raises(ValidationError):
        CallRecord(**_call_record(estimated_cost_usd=0.01))
    with pytest.raises(ValidationError):
        CorpusDoc(**_corpus_doc(trust="high"))


def test_a_parsed_record_cannot_be_mutated() -> None:
    """Evidence is not edited after it is recorded."""
    record = CallRecord(**_call_record())
    with pytest.raises(ValidationError):
        record.cost_usd = 0.0

    trace = CaseTrace(**_case_trace())
    with pytest.raises(ValidationError):
        trace.outcome_class = "ok"


# --------------------------------------------------------------------------
# 15 — the product catalog, T04's dependency
# --------------------------------------------------------------------------


def test_a_product_validates_and_a_bad_category_does_not() -> None:
    product = Product(**_product())
    assert (product.price_usd, product.stock) == (189.0, 12)

    with pytest.raises(ValidationError):
        Product(**_product(category="fish"))
    with pytest.raises(ValidationError):
        Product(**_product(care_level="expert"))
    with pytest.raises(ValidationError):
        Product(**_product(price_usd="189.00"))


def test_a_product_without_a_tank_size_is_valid() -> None:
    """An accessory has no minimum tank size, and `None` says so."""
    accessory = Product(
        **_product(id="AC-002", category="accessories", min_tank_size_gal=None)
    )
    assert accessory.min_tank_size_gal is None


# --------------------------------------------------------------------------
# 16 — derived cost, and the difference between None and zero
# --------------------------------------------------------------------------


def test_per_role_costs_sum_to_the_run_total() -> None:
    """T17's gate. Cost is derived from the `CallRecord`s rather than stored
    beside them, so the scorecard cannot report a total that disagrees with the
    calls it summarises."""
    candidate = CallRecord(**_call_record(cost_usd=0.002))
    judge = CallRecord(**_call_record(role="judge", metric="faithfulness", cost_usd=0.004))
    embedding = CallRecord(**_call_record(role="embedding", cost_usd=2e-07))

    run = RunArtifact(
        **_run_artifact(
            cases=[CaseTrace(**_case_trace(candidate_calls=[candidate], judge_calls=[judge]))],
            embedding_calls=[embedding],
        )
    )

    assert run.candidate_cost_usd == 0.002
    assert run.judge_cost_usd == 0.004
    assert run.embedding_cost_usd == 2e-07
    assert run.total_cost_usd == pytest.approx(0.002 + 0.004 + 2e-07)
    assert len(run.all_calls) == 3


def test_an_unreported_cost_totals_to_none_and_never_to_zero() -> None:
    """A fabricated `0.00` is the quietest way a cost claim becomes false. When
    no call reported a cost, the total is `None`, which the scorecard renders as
    "not reported by provider"."""
    silent = CallRecord(**_null_call_record())
    run = RunArtifact(
        **_run_artifact(cases=[CaseTrace(**_case_trace(candidate_calls=[silent]))])
    )

    assert run.candidate_cost_usd is None
    assert run.judge_cost_usd is None
    assert run.total_cost_usd is None


def test_a_reported_cost_is_not_diluted_by_a_silent_one() -> None:
    reported = CallRecord(**_call_record(cost_usd=0.002))
    silent = CallRecord(**_null_call_record())
    run = RunArtifact(
        **_run_artifact(
            cases=[CaseTrace(**_case_trace(candidate_calls=[reported, silent]))]
        )
    )
    assert run.candidate_cost_usd == 0.002


def test_the_infra_failure_rate_is_computed_over_cases() -> None:
    """T12 compares this against `config.INFRA_FAILURE_THRESHOLD`; above it the
    run is invalid and is not scored, which is not the same as failing."""
    ok = CaseTrace(**_case_trace())
    broken = CaseTrace(**_case_trace(case_id="G-015", outcome_class="provider_error"))

    assert RunArtifact(**_run_artifact(cases=[ok, ok, ok, broken])).infra_failure_rate == 0.25
    assert RunArtifact(**_run_artifact(cases=[])).infra_failure_rate == 0.0


def test_retrieval_accessors_preserve_order_and_deduplicate_docs() -> None:
    """T13's recall and reachability assertions read these."""
    first = RetrievedChunk(**_retrieved_chunk(chunk_id="policies/returns-2026#0", rank=0))
    second = RetrievedChunk(**_retrieved_chunk(chunk_id="policies/returns-2026#1", rank=1))
    third = RetrievedChunk(
        **_retrieved_chunk(
            chunk_id="faq#3",
            doc_id="faq",
            document_type="faq",
            authority="supporting",
            rank=2,
            score=0.55,
        )
    )

    trace = CaseTrace(**_case_trace(retrieved_chunks=[first, second, third]))
    assert trace.retrieved_chunk_ids == [
        "policies/returns-2026#0",
        "policies/returns-2026#1",
        "faq#3",
    ]
    assert trace.retrieved_doc_ids == ["policies/returns-2026", "faq"]


def test_case_token_totals_come_from_the_candidate_calls() -> None:
    trace = CaseTrace(
        **_case_trace(
            candidate_calls=[
                CallRecord(**_call_record(tokens_in=493, tokens_out=88)),
                CallRecord(**_call_record(tokens_in=120, tokens_out=40)),
            ]
        )
    )
    assert (trace.tokens_in, trace.tokens_out) == (613, 128)

    silent = CaseTrace(**_case_trace(candidate_calls=[CallRecord(**_null_call_record())]))
    assert (silent.tokens_in, silent.tokens_out) == (None, None)


# --------------------------------------------------------------------------
# Hashes are evidence, so they are validated like evidence
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_hash",
    ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, f"sha256:{'a' * 64}"],
)
def test_a_malformed_context_hash_is_rejected(bad_hash: str) -> None:
    with pytest.raises(ValidationError):
        CaseTrace(**_case_trace(retrieved_context_sha256=bad_hash))


def test_a_naive_timestamp_is_rejected() -> None:
    """Run timestamps are UTC and say so. A naive datetime is ambiguous
    evidence."""
    with pytest.raises(ValidationError):
        RunArtifact(**_run_artifact(started_at=datetime(2026, 7, 30, 18, 0)))


def test_a_run_cannot_finish_before_it_starts() -> None:
    """Clock skew or two timestamps passed in swapped order would otherwise
    round-trip cleanly and silently report a negative run duration in T17's
    scorecard. Every other cross-field invariant in this module is enforced at
    the type level rather than left to whoever reads the fields later."""
    with pytest.raises(ValidationError):
        RunArtifact(
            **_run_artifact(
                started_at=datetime(2026, 7, 30, 18, 4, tzinfo=UTC),
                finished_at=datetime(2026, 7, 30, 18, 0, tzinfo=UTC),
            )
        )


def test_a_run_finishing_the_instant_it_starts_is_valid() -> None:
    """Equal timestamps are a boundary, not an error — a zero-case smoke run
    could plausibly finish in the same instant it started."""
    same = datetime(2026, 7, 30, 18, 0, tzinfo=UTC)
    run = RunArtifact(**_run_artifact(started_at=same, finished_at=same))
    assert run.started_at == run.finished_at


def test_retrieval_evidence_accessors_agree_between_answer_result_and_case_trace() -> None:
    """`AnswerResult` and `CaseTrace` share one implementation of these
    accessors via `_RetrievalEvidence` — this pins them to producing identical
    output for identical input, so the two can't quietly drift apart."""
    chunks = [
        RetrievedChunk(**_retrieved_chunk(chunk_id="policies/returns-2026#0", rank=0)),
        RetrievedChunk(**_retrieved_chunk(chunk_id="policies/returns-2026#1", rank=1)),
    ]
    answer = AnswerResult(
        answer="Returns are accepted within 30 days [policies/returns-2026].",
        retrieved_chunks=chunks,
        retrieved_context_sha256=HASH_B,
        refused=False,
        outcome_class="ok",
        latency_ms=1420,
    )
    trace = CaseTrace(**_case_trace(retrieved_chunks=chunks))

    assert answer.retrieved_chunk_ids == trace.retrieved_chunk_ids
    assert answer.retrieved_doc_ids == trace.retrieved_doc_ids
