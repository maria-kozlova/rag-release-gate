"""Shared helpers for the T01 spike probes.

Throwaway code. Nothing in spike/ graduates to src/ — see PLAN.md T01.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"
BASE_URL = "https://openrouter.ai/api/v1"

CANDIDATE = "openai/gpt-4o-mini"
JUDGE = "anthropic/claude-haiku-4.5"
EMBED = "openai/text-embedding-3-small"


def api_key() -> str:
    load_dotenv(ENV_PATH)
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        sys.exit(f"OPENROUTER_API_KEY is empty. Paste your key into {ENV_PATH}")
    return key


def client():
    """The whole point of probe 1: the OpenAI SDK pointed at a different host."""
    from openai import OpenAI

    return OpenAI(base_url=BASE_URL, api_key=api_key())


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }


def rule(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def show(label: str, value: Any) -> None:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, indent=2, default=str)
    print(f"{label}: {value}")


def usage_dict(usage: Any) -> dict:
    """usage.cost is an OpenRouter extension the SDK does not type.

    Pydantic keeps unknown fields, so model_dump() is the honest way to see
    everything the provider actually sent instead of only what OpenAI declared.
    """
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage)
