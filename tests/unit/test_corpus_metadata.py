"""Checks over the corpus on disk — NOT the release gate. No key, no network.

Three documents in `data/corpus/` are wrong on purpose (see `data/FIXTURES.md`).
Most of this file exists to stop someone helpfully fixing them: a corpus whose
defects have been tidied away still passes every retrieval and judged metric,
while `conflict` and `injection` quietly test nothing. That is the quietest way
this project could end up dishonest, so the fixtures get assertions of their own.

This file parses the front-matter itself rather than calling into `ingest.py`.
That is deliberate — an independent reader means a parsing bug has to happen
twice before it goes unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import frontmatter
import pytest
from pydantic import ValidationError

from rag_release_gate.models import CorpusDoc, ProductCatalog

CORPUS = Path(__file__).resolve().parents[2] / "data" / "corpus"
PRODUCTS = CORPUS / "products.json"

FRONT_MATTER_KEYS = {"doc_id", "document_type", "status", "effective_date", "authority"}

# doc_id -> (document_type, status, authority). Every document in the corpus,
# named once, so a relabelling is an edit to this table and not a silent drift.
ASSIGNED_TRUST = {
    "policies/shipping": ("policy", "active", "authoritative"),
    "policies/returns-2026": ("policy", "active", "authoritative"),
    "policies/returns-2024-ARCHIVED": ("policy", "archived", "historical"),
    "guides/tank-sizing": ("guide", "active", "supporting"),
    "guides/species-compatibility": ("guide", "active", "supporting"),
    "guides/safety": ("guide", "active", "supporting"),
    "faq": ("faq", "active", "supporting"),
    "reviews/planted-tank-review": ("review", "active", "untrusted"),
    "products": ("product_catalog", "active", "authoritative"),
}

ARCHIVED_RETURNS = CORPUS / "policies" / "returns-2024-ARCHIVED.md"
REVIEW = CORPUS / "reviews" / "planted-tank-review.md"


def _markdown_docs() -> list[Path]:
    return sorted(CORPUS.rglob("*.md"))


def _front_matter(path: Path) -> dict[str, Any]:
    return frontmatter.loads(path.read_text(encoding="utf-8")).metadata


def _doc_id_for(path: Path) -> str:
    """The convention: path under `data/corpus/`, suffix stripped, forward slashes."""
    return path.relative_to(CORPUS).with_suffix("").as_posix()


def _catalog() -> ProductCatalog:
    """`model_validate_json`, never `json.loads` + `model_validate`. Strict mode
    accepts an ISO string for `effective_date` in JSON and rejects it in Python."""
    return ProductCatalog.model_validate_json(PRODUCTS.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 1 — front-matter is present, complete, and closed
# --------------------------------------------------------------------------


def test_every_markdown_doc_has_exactly_the_five_front_matter_keys() -> None:
    """Exactly five, not at least five. `CorpusDoc` is `extra="forbid"`, so a
    sixth key would fail validation at ingest — this fails it at review time."""
    docs = _markdown_docs()
    assert docs, "no markdown docs found — this loop would otherwise pass on nothing"
    for path in docs:
        assert set(_front_matter(path)) == FRONT_MATTER_KEYS, path


def test_every_document_validates_as_a_corpus_doc() -> None:
    """Covers the allowed `authority` and `document_type` sets, and the
    archived-implies-historical rule, through the type rather than by hand."""
    for path in _markdown_docs():
        CorpusDoc(**_front_matter(path))
    _catalog()


# --------------------------------------------------------------------------
# 2 — doc_id is the join key for every citation assertion downstream
# --------------------------------------------------------------------------


def test_every_doc_id_matches_its_path_and_is_unique() -> None:
    """T13 asserts on cited `doc_id`s. If one does not match its file, a valid
    citation looks invalid and the gate fails for a reason that is not a bug."""
    seen: list[str] = []
    for path in _markdown_docs():
        doc_id = _front_matter(path)["doc_id"]
        assert doc_id == _doc_id_for(path), path
        seen.append(doc_id)

    seen.append(_catalog().doc_id)
    assert len(seen) == len(set(seen)), f"duplicate doc_id in {seen}"


# --------------------------------------------------------------------------
# 3 — the archived rule, named explicitly by the T04 gate
# --------------------------------------------------------------------------


def test_an_archived_document_is_historical() -> None:
    """`SourceTrust` enforces this too. Kept explicit because it is the whole
    reason the archived returns policy can sit in context without being cited
    as current."""
    docs = _markdown_docs()
    assert docs, "no markdown docs found — this loop would otherwise pass on nothing"
    archived = [p for p in docs if _front_matter(p)["status"] == "archived"]
    assert archived, "no archived document found — this test would otherwise prove nothing"
    for path in archived:
        assert _front_matter(path)["authority"] == "historical", path


def test_every_document_carries_its_assigned_trust_labels() -> None:
    """Nothing else stops the review being relabelled `supporting`, which would
    neuter the entire untrusted path while every other test stayed green."""
    observed = {
        meta["doc_id"]: (meta["document_type"], meta["status"], meta["authority"])
        for meta in (_front_matter(p) for p in _markdown_docs())
    }
    catalog = _catalog()
    observed[catalog.doc_id] = (catalog.document_type, catalog.status, catalog.authority)

    assert observed == ASSIGNED_TRUST


# --------------------------------------------------------------------------
# 4 — volume floors: below these, retrieval is trivial and the metrics are noise
# --------------------------------------------------------------------------


def test_the_corpus_has_at_least_eight_markdown_documents() -> None:
    assert len(_markdown_docs()) >= 8


def test_products_json_validates_and_lists_at_least_fourteen_products() -> None:
    catalog = _catalog()
    assert len(catalog.products) >= 14
    assert {p.category for p in catalog.products} == {
        "aquatics",
        "reptiles",
        "small_mammals",
        "accessories",
    }


def test_a_duplicate_product_id_is_rejected() -> None:
    """`ProductCatalog._product_ids_are_unique` has no other test — the real
    `products.json` has no duplicate to exercise the rejection path with."""
    raw = _catalog().model_dump()
    raw["products"].append(raw["products"][0])
    with pytest.raises(ValidationError, match=raw["products"][0]["id"]):
        ProductCatalog(**raw)


# --------------------------------------------------------------------------
# 5 — the three deliberate defects. See data/FIXTURES.md.
# --------------------------------------------------------------------------


def test_the_stale_returns_window_appears_only_in_the_archived_policy() -> None:
    """The T04 gate asks for the literal "14 day". The regex below is the
    stronger form, not a wider one: a "14-day weather hold" written into the
    shipping policy would leave T10's `must_not_include: ["14 day"]` canary
    unable to distinguish a stale answer from a correct one."""
    assert "14 day" in ARCHIVED_RETURNS.read_text(encoding="utf-8")

    stale = re.compile(r"\b14[\s-]day", re.IGNORECASE)
    for path in sorted(CORPUS.rglob("*")):
        if path.is_dir() or path == ARCHIVED_RETURNS:
            continue
        assert not stale.search(path.read_text(encoding="utf-8")), path


def test_the_injection_canary_appears_only_in_the_review() -> None:
    """If BANANA leaks into a second document, T14's ASR = 0 stops being able to
    say which document the payload came from."""
    assert "BANANA" in REVIEW.read_text(encoding="utf-8")

    for path in sorted(CORPUS.rglob("*")):
        if path.is_dir() or path == REVIEW:
            continue
        assert "BANANA" not in path.read_text(encoding="utf-8"), path


def test_the_faq_price_contradicts_the_shipping_policy() -> None:
    """Conflict fixture #2 has no other guard. `faq.md` is `supporting` and
    `policies/shipping.md` is `authoritative`; $39.00 is the correct answer.
    "Fixing" the FAQ would leave T11's conflict cases with nothing to resolve."""
    shipping = (CORPUS / "policies" / "shipping.md").read_text(encoding="utf-8")
    faq = (CORPUS / "faq.md").read_text(encoding="utf-8")

    assert "$39.00" in shipping
    assert "$29.00" not in shipping
    assert "$29.00" in faq
    assert "$39.00" not in faq


# --------------------------------------------------------------------------
# 6 — conventions the later tickets rely on
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", _markdown_docs(), ids=_doc_id_for)
def test_every_document_body_opens_with_a_single_h1(path: Path) -> None:
    """T09 resolves a citation to a document title by reading this heading —
    there is no `title` front-matter key, because the gate says five keys."""
    body = frontmatter.loads(path.read_text(encoding="utf-8")).content
    h1s = [line for line in body.splitlines() if line.startswith("# ")]
    assert len(h1s) == 1, path
    assert body.lstrip().startswith("# "), path
