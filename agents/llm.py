"""The one place that talks to the LLM provider.

Every agent goes through get_client() / default_model(), so switching from
OpenRouter to another provider (or another model) only changes this file or
.env. OpenRouter speaks the OpenAI API, hence the openai package.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

OPENROUTER_URL = "https://openrouter.ai/api/v1"
FALLBACK_MODEL = "openai/gpt-4o-mini"
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def get_client() -> OpenAI:
    load_dotenv(_ENV_FILE)
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set: copy .env.example to .env and add your key")
    return OpenAI(base_url=OPENROUTER_URL, api_key=key)


def default_model() -> str:
    load_dotenv(_ENV_FILE)
    return os.getenv("PITWALL_MODEL") or FALLBACK_MODEL
