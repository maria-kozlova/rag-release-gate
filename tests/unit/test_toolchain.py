"""Guards on the toolchain configuration itself.

Cost hygiene is a setting in a file, and a setting in a file can be edited by
anyone — including a future agent session trying to make something green. These
checks make that edit visible.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_live_tests_are_deselected_by_default() -> None:
    """Without this, a paid test suite runs on every push."""
    addopts = _pyproject()["tool"]["pytest"]["ini_options"]["addopts"]
    assert "not live" in addopts


def test_live_marker_is_registered_and_strict() -> None:
    """An unregistered marker only warns; a typo would then deselect nothing."""
    ini = _pyproject()["tool"]["pytest"]["ini_options"]
    assert any(m.startswith("live:") for m in ini["markers"])
    assert "--strict-markers" in ini["addopts"]


def test_deepeval_is_pinned_exactly() -> None:
    """T01's routing evidence is a fact about 4.1.3, not about the library."""
    deps = _pyproject()["project"]["dependencies"]
    assert "deepeval==4.1.3" in deps


def test_rejected_dependencies_stay_rejected() -> None:
    """Each of these was excluded by a documented decision, not an oversight."""
    deps = " ".join(_pyproject()["project"]["dependencies"]).lower()
    for rejected in ("chromadb", "onnxruntime", "sentence-transformers", "litellm", "instructor"):
        assert rejected not in deps
