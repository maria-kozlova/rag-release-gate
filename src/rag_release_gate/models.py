"""Domain types and the evidence record.

Every model carries `strict=True, extra="forbid", frozen=True`: no silent
coercion (so `cost_usd="0.01"` is rejected instead of becoming a measured
float), no silently-dropped unknown keys, no editing evidence after it's
recorded.

Strict *Python* mode rejects a string for a `date` field; strict *JSON* mode
accepts it, since JSON has no native date type. So JSONL is read with
`model_validate_json()`, not `json.loads()` + `model_validate()` — see
`read_jsonl`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from rag_release_gate import config

DocumentType = Literal["policy", "product_catalog", "guide", "faq", "review"]
DocStatus = Literal["active", "archived"]
Authority = Literal["authoritative", "supporting", "historical", "untrusted"]

Category = Literal["factual", "synthesis", "policy", "refusal", "conflict", "injection"]
ExpectedBehavior = Literal["answer", "refuse"]

CallRole = Literal["candidate", "judge", "embedding"]
OutcomeClass = Literal["ok", "provider_error", "timeout"]
RunScope = Literal["smoke", "full"]

ProductCategory = Literal["aquatics", "reptiles", "small_mammals", "accessories"]
CareLevel = Literal["beginner", "intermediate", "advanced"]

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _Base(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class SourceTrust(_Base):
    """The trust block every corpus document carries and every chunk inherits."""

    document_type: DocumentType
    status: DocStatus
    effective_date: date
    authority: Authority

    @model_validator(mode="after")
    def _archived_documents_are_historical(self) -> SourceTrust:
        if self.status == "archived" and self.authority != "historical":
            raise ValueError(
                f"status='archived' requires authority='historical', got "
                f"{self.authority!r}: an archived policy may only be referenced "
                f"as superseded, never presented as current"
            )
        return self


class CorpusDoc(SourceTrust):
    doc_id: str


class Product(_Base):
    id: str
    name: str
    category: ProductCategory
    price_usd: float
    stock: int
    min_tank_size_gal: int | None
    care_level: CareLevel
    safety_notes: str | None


class Chunk(SourceTrust):
    chunk_id: str
    doc_id: str
    heading: str
    text: str


class RetrievedChunk(Chunk):
    score: float
    rank: int


class GoldenCase(_Base):
    """One line of `data/golden/golden.jsonl` — a case in the spec."""

    id: str
    category: Category
    question: str
    expected_behavior: ExpectedBehavior
    reference_answer: str | None
    expected_doc_ids: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    must_retrieve_doc_ids: list[str] = Field(default_factory=list)
    max_latency_ms: int = config.LATENCY_LOCAL_MAX_MS
    notes: str

    @model_validator(mode="after")
    def _reference_answer_matches_expected_behavior(self) -> GoldenCase:
        """Keyed on `expected_behavior`, not `category` — the false-refusal
        guard cases are `category="refusal"` with `expected_behavior="answer"`
        and need a reference answer. Keying this on `category` instead would
        make those cases unrepresentable."""
        if self.expected_behavior == "refuse" and self.reference_answer is not None:
            raise ValueError(
                f"case {self.id!r} expects a refusal but carries a reference_answer: "
                "there is no correct answer text to judge a refusal against"
            )
        if self.expected_behavior == "answer" and self.reference_answer is None:
            raise ValueError(
                f"case {self.id!r} expects an answer but has reference_answer=None: "
                "it would silently drop out of the judged tier"
            )
        return self


class CallRecord(_Base):
    """One model call — candidate, judge or embedding — recorded individually
    so per-role provenance (identity, cost) never collapses into a shared ID.

    `model_reported` is not constrained to equal `model_requested`: the
    embeddings endpoint echoes the model without its vendor prefix, so
    equality would fail on a correct system. Judge identity is asserted
    elsewhere, over `judge_calls`.
    """

    role: CallRole
    metric: str | None
    model_requested: str
    model_reported: str | None
    provider: str | None
    generation_id: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    latency_ms: int
    outcome_class: OutcomeClass


def _sum_cost(records: Iterable[CallRecord]) -> float | None:
    """`None` when nothing reported a cost — never `0.0`, which would claim
    the calls were free rather than admit the provider didn't say."""
    reported = [r.cost_usd for r in records if r.cost_usd is not None]
    return sum(reported) if reported else None


def _sum_tokens(values: Iterable[int | None]) -> int | None:
    reported = [v for v in values if v is not None]
    return sum(reported) if reported else None


class DeterministicResult(_Base):
    name: str
    passed: bool
    expected: str
    observed: str


class JudgeScore(_Base):
    metric: str
    score: float
    threshold: float
    reason: str | None


class MetricSummary(_Base):
    metric: str
    mean: float
    stdev: float | None
    n: int


class _RetrievalEvidence(_Base):
    """Shared by `AnswerResult` and `CaseTrace` so the two can't drift apart."""

    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)

    @property
    def retrieved_chunk_ids(self) -> list[str]:
        return [c.chunk_id for c in self.retrieved_chunks]

    @property
    def retrieved_doc_ids(self) -> list[str]:
        """Unique doc_ids in retrieval order."""
        seen: dict[str, None] = {}
        for chunk in self.retrieved_chunks:
            seen.setdefault(chunk.doc_id, None)
        return list(seen)


class AnswerResult(_RetrievalEvidence):
    """What `assistant.answer(question)` returns."""

    answer: str | None
    citations: list[str] = Field(default_factory=list)
    retrieved_context_sha256: Sha256
    refused: bool
    outcome_class: OutcomeClass
    latency_ms: int
    candidate_calls: list[CallRecord] = Field(default_factory=list)


class CaseTrace(_RetrievalEvidence):
    """One case's complete record — everything needed to reconstruct what
    happened without rerunning it. `deterministic_results` and `judge_scores`
    default empty; the gate tiers fill them in after the fact."""

    case_id: str
    question: str
    category: Category
    candidate_model: str
    candidate_temperature: float
    candidate_max_tokens: int | None
    judge_model: str
    judge_temperature: float
    judge_strict_mode: bool
    system_prompt_version: str
    system_prompt_sha256: Sha256
    retrieval_k: int
    retrieved_context_sha256: Sha256
    index_manifest_sha256: Sha256
    answer: str | None
    citations: list[str] = Field(default_factory=list)
    refused: bool
    outcome_class: OutcomeClass
    latency_ms: int
    deterministic_results: list[DeterministicResult] = Field(default_factory=list)
    judge_scores: list[JudgeScore] = Field(default_factory=list)
    candidate_calls: list[CallRecord] = Field(default_factory=list)
    judge_calls: list[CallRecord] = Field(default_factory=list)

    @property
    def tokens_in(self) -> int | None:
        return _sum_tokens(c.tokens_in for c in self.candidate_calls)

    @property
    def tokens_out(self) -> int | None:
        return _sum_tokens(c.tokens_out for c in self.candidate_calls)

    @property
    def candidate_cost_usd(self) -> float | None:
        return _sum_cost(self.candidate_calls)

    @property
    def judge_cost_usd(self) -> float | None:
        return _sum_cost(self.judge_calls)


class RunArtifact(_Base):
    """One evaluation run — what T13, T14 and T15 all assert over."""

    run_id: str
    started_at: AwareDatetime
    finished_at: AwareDatetime
    git_sha: str | None
    scope: RunScope
    suite_version: str
    candidate_model: str
    judge_model: str
    embedding_model: str
    system_prompt_version: str
    system_prompt_sha256: Sha256
    index_manifest_sha256: Sha256
    retrieval_k: int
    cases: list[CaseTrace] = Field(default_factory=list)
    embedding_calls: list[CallRecord] = Field(default_factory=list)
    metric_summaries: list[MetricSummary] = Field(default_factory=list)
    infra_failure: bool = False

    @model_validator(mode="after")
    def _finished_at_is_not_before_started_at(self) -> RunArtifact:
        if self.finished_at < self.started_at:
            raise ValueError(
                f"finished_at ({self.finished_at}) is before started_at "
                f"({self.started_at}): a run cannot end before it starts"
            )
        return self

    @property
    def candidate_cost_usd(self) -> float | None:
        return _sum_cost(c for case in self.cases for c in case.candidate_calls)

    @property
    def judge_cost_usd(self) -> float | None:
        return _sum_cost(c for case in self.cases for c in case.judge_calls)

    @property
    def embedding_cost_usd(self) -> float | None:
        return _sum_cost(self.embedding_calls)

    @property
    def total_cost_usd(self) -> float | None:
        """Derived, not stored, so it can't drift from the calls it sums."""
        per_role = [self.candidate_cost_usd, self.judge_cost_usd, self.embedding_cost_usd]
        reported = [c for c in per_role if c is not None]
        return sum(reported) if reported else None

    @property
    def all_calls(self) -> list[CallRecord]:
        calls = [c for case in self.cases for c in case.candidate_calls]
        calls += [c for case in self.cases for c in case.judge_calls]
        return calls + list(self.embedding_calls)

    @property
    def infra_failure_rate(self) -> float:
        if not self.cases:
            return 0.0
        bad = sum(1 for case in self.cases if case.outcome_class != "ok")
        return bad / len(self.cases)


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> int:
    """Write one JSON object per line to `path`. Returns the count written.

    No `exclude_none` — a field the provider didn't report must survive as an
    explicit `null`, not silently drop out and let a reader's default refill
    it. `newline="\\n"` because Windows would otherwise write CRLF, and these
    bytes feed SHA-256 hashes elsewhere.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(record.model_dump_json())
            handle.write("\n")
            count += 1
    return count


def read_jsonl[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    """Parse a JSONL file into validated models, one per non-blank line.

    For inputs under `data/` only — never point this at `reports/` or
    `traces.jsonl`; a previous run's answers are never an input to a test.
    """
    parsed: list[M] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                parsed.append(model.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{lineno}: does not validate as {model.__name__}:\n{exc}"
                ) from exc
    return parsed
