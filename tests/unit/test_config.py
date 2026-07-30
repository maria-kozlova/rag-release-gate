"""Unit checks over config — NOT the release gate. No key, no network."""

from __future__ import annotations

from rag_release_gate import config


def test_the_three_model_roles_are_pinned() -> None:
    assert config.CANDIDATE_MODEL == "openai/gpt-4o-mini"
    assert config.JUDGE_MODEL == "anthropic/claude-haiku-4.5"
    assert config.EMBEDDING_MODEL == "openai/text-embedding-3-small"


def test_candidate_and_judge_are_different_families() -> None:
    """The self-preference-bias mitigation, asserted at the config level.

    T15 asserts it again per judge call at run time; this catches the mistake
    at the source, before a run ever costs money.
    """
    candidate_vendor = config.CANDIDATE_MODEL.split("/")[0]
    judge_vendor = config.JUDGE_MODEL.split("/")[0]
    assert candidate_vendor != judge_vendor, (
        f"candidate and judge are both {candidate_vendor}: "
        "a same-family judge reintroduces self-preference bias"
    )


def test_embedding_dimension_matches_the_pinned_model() -> None:
    assert config.EMBEDDING_DIM == 1536
